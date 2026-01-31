import socket
from zeroconf import ServiceInfo, Zeroconf
import zeroconf
from app import run_chat


def start_mdns(username, ip ,port):
    zeroconf=Zeroconf()
    service_type="_naval._tcp.local."
    service_name=f"{username}.{service_type}"
    info=ServiceInfo(service_type, service_name, addresses=[socket.inet_aton(ip)], port=port, properties={
        b"user": username.encode(),
        b"ver": b"1.2"
    })
    zeroconf.register_service(info)
    return zeroconf, info


def get_local_ip():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()
def aport(ip, ports):
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    for port in ports:
        try:
            s.bind((ip, port))
            return s,port
        except OSError:
            continue
    raise RuntimeError("No available ports!")

def server():
    ports=[5000,5001]
    ip= get_local_ip()
    s, port=aport(ip,ports)
    username=input("Enter your username: ").strip()
    zeroconf= start_mdns(username, ip, port)

    s.listen(1)
    print("Listening...")

    conn, addr =s.accept()
    print("connected from", addr)
    run_chat(conn, username)
    
if __name__ == "__main__":
    server()

