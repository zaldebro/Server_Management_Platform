import asyncio
import functools
import json
import paramiko
import select
import websockets
import requests


serverip = "192.168.3.28"  # 获取 paramiko 连接的IP地址，CMDB服务端IP地址
hostname = "192.168.3.28"  # paramiko连接地址，当前端没有返回IP地址时，默认使用该地址
user = "root"  # paramiko 登录用户名
sshFile = "/root/.ssh/id_rsa"  # 密钥路径

private_key = paramiko.RSAKey.from_private_key_file(sshFile)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())


async def echo(websocket, path, client):
    async for message in websocket:
        flag = True
        res = requests.get(f"http://{serverip}:5000/ssh/getip")
        if res.status_code == 200:
            tmpIp = (json.loads(res.text)).get('ip')
            if tmpIp == "notip":
                await websocket.send("无法找到目标主机！")
                flag = False
        else:
            await websocket.send("CMDB服务是否已经启动？")
            flag = False

        if flag:
            global hostname
            if tmpIp == hostname:
                pass
            elif tmpIp != hostname:
                hostname = tmpIp
                await websocket.send("若是长时间未反应，请检查免密设置")
                client.connect(hostname=hostname, port=22, username=user, pkey=private_key, compress=True)
                channel = client.invoke_shell()  # 开启终端
                # channel.settimeout(10) 设置超时时间
            # else:
            #     client.connect(hostname=hostname, port=22, username=user, pkey=private_key, compress=True)
            try:
                # 当上次连接和本次连接同一台服务器时，连接超时，channel不存在，需要重新连接
                channel.send(message + '\n')
            except:
                await websocket.send("若是长时间未反应，请检查免密设置")
                client.connect(hostname=hostname, port=22, username=user, pkey=private_key, compress=True)
                channel = client.invoke_shell()
                channel.settimeout(10)
                channel.send(message + '\n')

            stdout = ""
            while True:
                rl, wl, xl = select.select([channel], [], [], 0.5)
                if len(rl) > 0:
                    restdoutcv = channel.recv(65536).decode()
                    stdout += restdoutcv
                else:
                    break
            await websocket.send(stdout)


start_server = websockets.serve(functools.partial(echo, client=client), '0.0.0.0', 8765)

# asyncio.run(start_server)
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
