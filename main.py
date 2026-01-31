from server import server
from client import client

print("Press:\n1. Host\n2. Connect")
choice=int(input("Enter the what you want to do: "))
if choice==1:
    server()
else:
    client()