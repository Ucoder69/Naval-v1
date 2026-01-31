import hashlib
import threading
import protocol
import transport
import os
import time
from queue import Queue
import encryption as en
from tuning import Tuner

conn_alive= True
TUNER=Tuner()
probe_event=threading.Event()
probe_sent_time=None
probe_rtt=None
CURRENT_SESSION = 0
# max payload 4GB. turbo mode at 128amxsize at 1MB rate or 128 at 4 or at at 8MBPS!!
send_queue=Queue(maxsize=64)

def send_system(conn, message: str):
    payload = message.encode("utf-8")
    header = (
        protocol.e_type("System") + protocol.e_length(len(payload))
    )
    conn.sendall(header)
    conn.sendall(payload)

def send_frame(conn, msg_type, payload: bytes):

    header = (
        protocol.e_type(msg_type) + protocol.e_length(len(payload))
    )
    conn.sendall(header)
    conn.sendall(payload)
    
def auto_tune(conn):
    global probe_sent_time, probe_rtt

    # ---- RTT PROBE ----
    probe_event.clear()
    probe_sent_time = time.time()
    send_system(conn, "PING")

    if not probe_event.wait(timeout=1.0):
        # Fallback if probe fails
        return {
            "chunk": 512 * 1024,
            "queue": 64,
            "mode": "Balanced"
        }
    rtt_ms = probe_rtt * 1000 # type: ignore
    # ---- MODE SELECTION ----
    if rtt_ms <= 3:
        return {
            "chunk": 4 * 1024 * 1024,
            "queue": 128,
            "mode": "Extreme"
        }
    if rtt_ms <= 6:
        return {
            "chunk": 1 * 1024 * 1024,
            "queue": 128,
            "mode": "Turbo"
        }
    return {
        "chunk": 512 * 1024,
        "queue": 64,
        "mode": "Balanced"
    }

    
def send_file(conn, cipher, path):
    TUNER.begin_transfer()
    session = TUNER.session_id
    sha=hashlib.sha256() 
    filename= os.path.basename(path)
    total_size=os.path.getsize(path)
    sent=0
    send_frame(conn, "File", f"META:{session}:{filename}".encode("utf-8"))
    with open(path, "rb") as f:
        start_time= time.time()
        last_update= start_time
        while True:
            chunk= f.read(TUNER.chunk_size)
            if not chunk:
                break
            encrypted=cipher.encrypt(chunk)
            # encrypted=chunk
            sha.update(chunk)
            send_queue.put(("File", encrypted))
            sent+=len(chunk)

            now = time.time()
            elapsed = now - start_time
            if sent> total_size:
                sent= total_size
                
            if elapsed > 0:
                speed = sent / elapsed           # bytes/sec
                remaining = total_size - sent

                if speed > 0 and now - last_update >= 2.0:
                    eta = remaining / speed

                    percent = (sent / total_size) * 100
                    speed_mb = speed / (1024 * 1024)

                    eta_min = int(eta // 60)
                    eta_sec = int(eta % 60)

                    print(
                                    f"\rSent {sent/(1024*1024):.1f}MB / {total_size/(1024*1024):.1f}MB "
                                    f"({percent:.1f}%) | {speed_mb:.1f} MB/s | ETA {eta_min:02}:{eta_sec:02}",
                                    end=""
                                )
                    last_update = now
    send_queue.join()
    send_queue.put(("System", b"FILE_END"))
    file_hash= sha.hexdigest()
    payload2=f"FILE_HASH:{file_hash}"
    send_queue.put(("System", payload2.encode()))
    TUNER.end_transfer()
    print(f"\n[file sent: {filename}]")

def network_sender(conn):
    while True:
        item= send_queue.get()
        if item is None:
            break
        
        msg_type, payload = item
        send_frame(conn, msg_type, payload)
        send_queue.task_done()
    
def run_chat(conn, username):
    global conn_alive
    os.makedirs("received_files", exist_ok=True)  
    password=input("Enter shared password: ")
    key= en.derive_key(password)
    cipher= en.AESGCMCipher(key)
    send_system(conn, f"JOIN:{username}")
    
    tuning = auto_tune(conn)
    CHUNK_SIZE = tuning["chunk"]
    print(f"[AutoTune] Mode={tuning['mode']} | Chunk={CHUNK_SIZE//1024}KB | Queue={tuning['queue']}")
    
    t=threading.Thread(target=receiver_loop, args=(conn, cipher,), daemon=True)
    net_thread= threading.Thread(target=network_sender, args=(conn, ), daemon=True)
    net_thread.start()
    t.start()
    sender_loop(conn,username, cipher,)
    
def receiver_loop(conn, cipher):
    global conn_alive
    exp_file=False
    current_file=None
    file_handle=None
    received_bytes=0
    sha=hashlib.sha256()
    
    try:   
        while True:    
            header=transport.read_exactly(conn, 5)
            t= protocol.d_type(header[0:1])  
            l= protocol.d_length(header[1:5])  
            payload = transport.read_exactly(conn, l)
             
            if t==1:
                txt=cipher.decrypt(payload).decode("utf-8")
                print(f"{name}:", txt)
            elif t==2:
                payload=payload.decode("utf-8")
                
                if payload.startswith("JOIN:"):
                    name=payload[5:]
                    print(f"[{name} joined]")
                elif payload.startswith("LEAVE:"):
                    name=payload[6:]
                    print(f"[{name} left]")
                    break
                elif payload=="PING":
                    send_system(conn, "PONG")
                elif payload=="PONG":
                    global probe_rtt, probe_sent_time
                    probe_rtt=time.time()-probe_sent_time # type: ignore
                    probe_event.set()
                elif payload=="FILE_END":
                    local_hash=sha.hexdigest()
                    if file_handle:
                        file_handle.close()
                        print(f"\nFile received: {current_file}")
                    exp_file=False
                    current_file=None
                    file_handle=None
                    received_bytes=0
                elif payload.startswith("FILE_HASH:"):
                    sender_hash=payload.split(":", 1)[1]
                    if sender_hash==local_hash:
                        print("File Verified")
                    elif local_hash is None:
                        print("Protocol Error: hash received before file end")
                    else:
                        print("File corrupted")
                        #os.remove(path)     
                    local_hash= None
                    sha=hashlib.sha256()           
            elif t==3:
                if not exp_file:
                    if not payload.startswith(b"META:"):
                        continue
                    meta = payload.decode("utf-8")
            
                    _, recv_session , current_file = meta.split(":", 2)

                    # if int(recv_session) != TUNER.session_id:
                    #     print("whut")
                    #     # stale transfer, ignore safely
                    #     continue

                    path = os.path.join("received_files", current_file) # type: ignore
                    file_handle = open(path, "wb")

                    received_bytes = 0
                    sha=hashlib.sha256()
                    exp_file= True
                else:
                    decrypted_chunk :bytes= cipher.decrypt(payload)      
                    # decrypted_chunk= payload              
                    file_handle.write(decrypted_chunk)  # type: ignore
                    sha.update(decrypted_chunk)
                    received_bytes +=len(decrypted_chunk)
                    print(f"\rReceived {received_bytes/(1024*1024):.1f} MB", end='')
                                        
    except NameError as e:
        conn_alive=False
        if exp_file:
            if file_handle: 
                print("\nFile transfer interrupted")
        print("receiver stopped", e)

def sender_loop(conn, username,cipher):
    global conn_alive
    global send_queue
    try:
        while conn_alive:
            if not conn_alive:
                break
            
            txt=input("You:").strip()
            if txt.strip()=="/quit":
                send_system(conn, f"LEAVE:{username}")
                send_queue.put(None)
                conn.close()
                break
            
            elif txt.startswith("/send "): 
                path=txt[6:].strip()
                if not os.path.isfile(path):
                    print("File not Found")
                    continue
                send_file(conn, cipher, path)
                continue
            elif txt.startswith("/mode "):
                parts = txt.split(" " ,maxsplit=1)

                if len(parts) == 1 or parts[1] == "status":
                    print(TUNER.status())
                    continue

                success, msg = TUNER.apply_mode(parts[1].lower())
                if success:
                    global CURRENT_SESSION
                    CURRENT_SESSION=TUNER.session_id
                print(msg)

                # Apply queue resize safely (NO replacement)
                send_queue.maxsize = TUNER.queue_size
                continue

            payload=cipher.encrypt(txt.encode("utf-8"))
            send_frame(conn, "Text", payload)
            
    except (ConnectionResetError, BrokenPipeError): #added later
        conn_alive=False
        print(f"{username} disconnected!")