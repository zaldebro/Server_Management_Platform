import datetime
import json
import subprocess

import pymysql
import redis
import time
import urllib.parse
import urllib.request as nrequest
import requests
import paramiko

from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from dbutils.pooled_db import PooledDB
from pymysql.converters import escape_string

from config import globalConfig

# 导入相关配置参数
host = globalConfig["host"]
user = globalConfig["user"]
MySQLpasswd = globalConfig["MySQLpwd"]
Redispwd = globalConfig["Redispwd"]
serverpasswd = globalConfig["serverpasswd"]
FuZeRen = globalConfig["负责人"]
id_rsa = globalConfig["id_rsa"]

pool = PooledDB(creator=pymysql, host=host, user=user, passwd=MySQLpasswd, mincached=10)

r = redis.Redis(host=host, port=6379, password=Redispwd)


# 创建钉钉类，实现使用钉钉的基本操作
class DingDing():
    def __init__(self, AGENT_ID, appkey, appsecret, processCode):
        self.AGENT_ID = AGENT_ID
        self.appkey = appkey
        self.appsecret = appsecret
        self.processCode = processCode

    # 获取access_token
    def get_token(self):
        res = requests.get("https://oapi.dingtalk.com/gettoken?appkey=%s&appsecret=%s" % (self.appkey, self.appsecret))
        if res.status_code == 200:
            str_res = res.text
            token = (json.loads(str_res)).get('access_token')
            # print(token, "token=-=-=")
            return token

    # 发送消息
    def post_message(self, userid, send_msg_info):
        msg = {}
        msg["userid_list"] = userid
        msg["agent_id"] = self.AGENT_ID
        msg["msg"] = {}
        msg["msg"]["msgtype"] = "text"
        msg["msg"]["text"] = {}
        msg["msg"]["text"]["content"] = str(send_msg_info)
        postData = urllib.parse.urlencode(msg)
        postData = postData.encode('utf-8')
        nrequest.urlopen(
            'https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2?access_token=%s' % self.get_token(),
            postData)

    # 获取部门的子部门列表
    def getDepartmentSubList(self):

        url = "https://oapi.dingtalk.com/department/list?access_token={}&lang=zh_CN&fetch_child=false&id={}".format(
            self.get_token(), 865095136)
        res = requests.get(url)
        subDepartment = res.text
        subDepartment = json.loads(subDepartment)
        # 研发中心 - 安全能力研发部 - 数据与能力中台研发部
        print("subList-->", subDepartment)
        subList = []
        for Department in subDepartment["department"]:
            print("name-->", Department["name"])
            subList.append(Department["id"])
        return subList

    # 根据部门获取员工信息
    def getUseridByDepartment(self, departmentId, name):
        cursor = 0
        size = 100
        url = 'https://oapi.dingtalk.com/topapi/v2/user/list?access_token=%s' % self.get_token()
        print("token --> ", self.get_token())
        # 当查询到第九百个员工时，停止继续查询，可减小
        while cursor <= 900:
            body = {
                "dept_id": departmentId,
                "cursor": cursor,
                "size": size
            }
            response = requests.post(url, data=body)
            content = response.json()
            print('content--> ', content)
            if content["errcode"] == 0:
                for info in content["result"]["list"]:
                    # redis 设置过期时间86,400s（一天），防止缓存影响离职信息通知
                    r.set(info["name"], info["userid"], ex=86400)
                    if info["name"] == str(name):
                        # r.set(str(name), info["userid"], ex=5000)
                        return info["userid"]
                cursor += 100
            else:
                return False
        else:
            return False

    # 根据员工姓名获取userid
    def get_userid(self, name):
        if name is not None and name:
            userid = r.get(name)
            if userid is not None:
                print("Redis userid--> ", userid)
                return userid
            else:
                subList = self.getDepartmentSubList()
                print("subList-->", subList)
                for subDepartmentId in subList:
                    userid = self.getUseridByDepartment(subDepartmentId, name)
                    print("userid--> ", userid)
                    if userid:
                        return userid
                else:
                    return False

    # 根据员工userid获取用户名
    def get_username(self, userid):
        url = "https://oapi.dingtalk.com/user/get?access_token={}&userid={}".format(self.get_token(), userid)
        res = requests.get(url)
        userinfo = res.text
        userinfo = json.loads(userinfo)
        # print("userinfo-->", userinfo)
        return userinfo["name"]

    def getDepartmentInfo(self, departmentId):
        url = "https://oapi.dingtalk.com/department/get?access_token={}&id={}&lang=zh_CN".format(self.get_token(),
                                                                                                 departmentId)
        res = requests.get(url)
        departmentInfo = res.text
        departmentInfo = json.loads(departmentInfo)
        print("departmentInfo-->", departmentInfo)
        return departmentInfo["name"]

    # 获取钉钉表单信息
    def SDKList(self):
        dt = '2023-08-20 12:00:00'  # 表示当前获取的数据开始时间
        time.strptime(dt, '%Y-%m-%d %H:%M:%S')
        time1 = int(time.mktime(time.strptime(dt, '%Y-%m-%d %H:%M:%S')))
        time1 = str(time1) + '000'  # 对时间戳进行转换
        url = 'https://oapi.dingtalk.com/topapi/processinstance/list?access_token={}&process_code={}' \
            .format(self.get_token(), self.processCode)

        data = {
            'process_code': self.processCode,
            'start_time': time1,
        }

        data1 = json.dumps(data).encode(encoding='UTF8')

        result = requests.post(url=url, data=data1, headers={"Content-Type": "application/json", "Charset": "UTF-8"})
        ret = json.loads(result.text)
        # print("ret->", ret)
        sdk_info = ret.get('result').get('list')
        return sdk_info


# 定义apscheduler的执行器参数
executors = {
    'default': ThreadPoolExecutor(20),  # 默认线程数
    'processpool': ProcessPoolExecutor(3)  # 默认进程
}

# 当 APScheduler 的所有线程均被使用时，会默认抛弃其他任务
# 设置 coalesce 为 True，当一个任务被错过多次时，只执行一次
# 设置 misfire_grace_time 为None，无论错过多少个任务都会被执行
job_defaults = {
    'coalesce': True,
    'misfire_grace_time': None,
}

# 生成任务调度器
scheduler = BackgroundScheduler(timezone='Asia/Shanghai', executors=executors,
                                job_defaults=job_defaults)  # jobstores=jobstores,持久化参数，不好用

# # 启动任务调度器
scheduler.start()

import urllib3
from vmware.vapi.vsphere.client import create_vsphere_client

ip = 'xxx.xxx.xxx.xxx'
user = 'xxxxxx
password = 'xxxxx'

session = requests.session()
session.verify = False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# 连接到vCenter服务器
client = create_vsphere_client(server=ip, username=user, password=password, session=session)

private = paramiko.RSAKey.from_private_key_file(id_rsa)
ssh_client = paramiko.SSHClient()
ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())


# 分配服务器函数，这里了修改服务器密码为初始密码；分配服务器时执行的任务等修改在这里
def distributeServer(ip):
    try:
        serverpasswd = globalConfig["serverpasswd"]
        ssh_client.connect(
            hostname=str(ip),
            port=22,
            username='root',
            pkey=private,
            timeout=3
        )

    except:
        return False

    stdin, stdout, stderr = ssh_client.exec_command(
        f'echo "{serverpasswd}" | passwd root --stdin')
    if stderr.read().decode("utf8"):
        return False
    else:
        return True


# 服务器资产到期对服务器修改密码和关闭docker服务；回收服务器时执行的任务修改等在这里
def offServer(IPaddress, ZeRenRen):
    try:
        ssh_client.connect(
            hostname=str(IPaddress),
            port=22,
            username='root',
            pkey=private
        )

        offserverpasswd = globalConfig["offserverpasswd"]

        # ssh root@192.168.5.140 'echo "123" | passwd root --stdin'
        stdin, stdout, stderr1 = ssh_client.exec_command(f'echo "{offserverpasswd}" | passwd root --stdin')
        stdin, stdout, stderr2 = ssh_client.exec_command("systemctl stop docker")

        # 如果有错误输出，则通知管理员关闭服务操作失败
        if stderr1.read().decode("utf8") or stderr2.read().decode("utf8"):
            dingding.post_message(dingding.get_userid(FuZeRen),
                                  "用户" + str(ZeRenRen) + "的服务器， IP地址为" + str(IPaddress) + "修改密码或关闭docker失败，回收失败")
        else:
            dingding.post_message(dingding.get_userid(FuZeRen),
                                  "用户" + str(ZeRenRen) + "的服务器， IP地址为" + str(IPaddress) + "已回收")
        ssh_client.close()
    except:
        dingding.post_message(dingding.get_userid(FuZeRen),
                              "用户" + str(ZeRenRen) + "的服务器， IP地址为" + str(IPaddress) + "已到期，回收失败")


# 定时任务，检测数据库中的到期时间；对服务器到期通知修改等在这里
def serverinfo_job():
    FuZeRenid = dingding.get_userid(FuZeRen)
    sql = 'SELECT `责任人`,`IP地址`,`到期时间`,`机房`, `序号`,`用途` FROM CMDB.server;'
    db = pool.connection()
    cursor = db.cursor()
    cursor.execute(sql)
    infos = cursor.fetchall()
    cursor.close()
    db.close()
    for info in infos:
        ZeRenRen, IPaddress, endtime, JiFang, XuHao, YongTu = info

        if endtime is not None and ZeRenRen != "已回收":

            # 如果查询不到 该责任人相关的id信息，则通知管理员
            ZeRenRenid = dingding.get_userid(ZeRenRen)

            if not ZeRenRenid:
                msgtoAdmin = "未查询到 " + str(ZeRenRen) + " 的id信息！"
                dingding.post_message(FuZeRenid, msgtoAdmin)
                continue

            # 对查询到的结束时间格式化处理
            endtime = datetime.datetime.strptime(endtime, "%Y-%m-%d").date()
            nowtime = time.strftime('%Y-%m-%d', time.localtime())
            nowtime = datetime.datetime.strptime(nowtime, "%Y-%m-%d").date()
            deltatime = (endtime - nowtime).days

            # 对服务没有运行期间资产到期进行检查并且发送通知
            if deltatime < 0 and ZeRenRen != "已回收":
                sql = f'UPDATE CMDB.server SET `部门`="已回收",`责任人`="已回收",`服务状态`="未使用" WHERE `序号`="{XuHao}"'
                db = pool.connection()
                cursor = db.cursor()
                cursor.execute(sql)
                db.commit()
                cursor.close()
                db.close()
                msgtoApplicants = "服务器IP地址为" + str(IPaddress) + "，用途为 " + str(YongTu) + "已回收"
                dingding.post_message(FuZeRenid, msgtoApplicants)

            elif deltatime in [0, 5, 10]:
                # 如果服务器在外网，则执行相关动作；否则仅通知
                if deltatime == 0 and ZeRenRen != "已回收":
                    sql = f'UPDATE CMDB.server SET `部门`="已回收",`责任人`="已回收",`服务状态`="未使用" WHERE `序号`="{XuHao}"'
                    if JiFang == "外网":
                        msgtoApplicants = "您的服务器" + str(IPaddress) + "，用途为 " + str(YongTu) + " 已到期"
                        dingding.post_message(ZeRenRenid, msgtoApplicants)
                        offServer(IPaddress=IPaddress, ZeRenRen=ZeRenRen)
                    else:
                        msgtoApplicants = "您的服务器" + str(IPaddress) + "，用途为 " + str(YongTu) + " 已到期"
                        msgtoAdmin = "用户" + str(ZeRenRen) + "的内网服务器， IP地址为" + str(IPaddress) + "已到期"
                        dingding.post_message(ZeRenRenid, msgtoApplicants)
                        dingding.post_message(FuZeRenid, msgtoAdmin)
                    db = pool.connection()
                    cursor = db.cursor()
                    cursor.execute(sql)
                    db.commit()
                    cursor.close()
                    db.close()
                else:
                    msgtoApplicants = '您的服务器' + str(IPaddress) + "，用途为 " + str(YongTu) + '还有' + str(deltatime) + '天到期！'
                    dingding.post_message(ZeRenRenid, msgtoApplicants)


# 虚拟机资源到期提醒；对虚拟机到期时间修改等在这里
def vmserverinfo_job():
    sql = f'SELECT `责任人`,`虚拟机名称`, `结束时间`, `虚拟机id` FROM CMDB.vmserver'
    db = pool.connection()
    cursor = db.cursor()
    cursor.execute(sql)
    infos = cursor.fetchall()

    for info in infos:
        ZeRenRen, VmName, endtime, vmid = info

        if endtime and endtime is not None:

            endtime = datetime.datetime.strptime(endtime, "%Y-%m-%d").date()
            nowtime = time.strftime('%Y-%m-%d', time.localtime())
            nowtime = datetime.datetime.strptime(nowtime, "%Y-%m-%d").date()

            deltatime = (endtime - nowtime).days

            if deltatime <= 0 and ZeRenRen != "已回收":
                try:
                    client.vcenter.vm.Power.stop(vmid)
                except:
                    dingding.post_message(dingding.get_userid(FuZeRen),
                                          "虚拟机 " + str(VmName) + "id为：" + str(vmid) + " 到期回收异常")
                sql = f'UPDATE CMDB.vmserver SET `责任人`="已回收" WHERE `虚拟机id`="{vmid}";'
                cursor.execute(sql)
                db.commit()
                dingding.post_message(dingding.get_userid(str(ZeRenRen)), send_msg_info="虚拟机 " + str(VmName) + " 已回收！")

    cursor.close()
    db.close()


# 测试密钥文件登录函数
def keySsh(ipAddress, pkey):
    try:
        client.connect(hostname=ipAddress, port=22, username="root", pkey=pkey, timeout=1)
        return True
    except:
        return False


# 检测主机是否可达
def sshTestJob():
    unreachableHostList = []
    # 设置 sshFlag 如果使用密钥文件ssh失败，使用密码登录成功，则 sshFlag = True 执行免密脚本
    # sshFlag = True

    # 每次执行本定时任务时，清空上一次不可达的主机信息
    sql = "TRUNCATE TABLE CMDB.unreachHost;"

    db = pool.connection()
    cursor = db.cursor()

    cursor.execute(sql)
    db.commit()

    password = globalConfig["serverpasswd"]

    sql = "select `IP地址` from CMDB.server;"
    cursor.execute(sql)
    serverInfos = cursor.fetchall()

    print(serverInfos)

    for serverInfo in serverInfos:
        ipAddress = serverInfo[0]

        status = keySsh(ipAddress=ipAddress, pkey=private)
        # 如果密钥登陆失败，则尝试使用默认密码登录
        if status:
            continue
        else:
            try:
                msgtoAdmin = "服务器 " + str(ipAddress) + " 需要执行免密操作"
                dingding.post_message(dingding.get_userid(FuZeRen), msgtoAdmin)
                client.connect(hostname=ipAddress, port=22, username="root", password=password, timeout=1)
            except:
                unreachableHostList.append(ipAddress)
                msgtoAdmin = "服务器 " + str(ipAddress) + " 不可达"
                print("主机 " + ipAddress + " 不可达")
                dingding.post_message(dingding.get_userid(FuZeRen), msgtoAdmin)
                # sshFlag = False

        # if sshFlag:
        #     command = f"bash /usr/local/CMDB/script/sshOnly.sh {ipAddress}"
        #     task = subprocess.Popen(command, shell=True)
        #     task.wait()
        #     # 如果异常，通知管理员
        #     print("task.poll()-->", task.poll())
        #     if task.poll() == 0:
        #         continue
        #     else:
        #         msgtoAdmin = "服务器 " + str(ipAddress) + " 执行免密失败"
        #         print("主机 " + ipAddress + " 不可达")
        #         dingding.post_message(dingding.get_userid(FuZeRen), msgtoAdmin)

    print(unreachableHostList)
    # 如果 unreachableHostList 有不可达的主机
    if unreachableHostList:
        for unreachableHost in unreachableHostList:
            sql = f'INSERT INTO CMDB.unreachHost VALUES("{unreachableHost}");'
            cursor.execute(sql)
        db.commit()

    cursor.close()
    db.close()


# 获取钉钉表单信息，并执行相关任务
def corn_job(FuZeRen):
    FuZeRenid = dingding.get_userid(FuZeRen)
    print("开始执行钉钉表单任务")

    sdk_info = dingding.SDKList()
    print("sdk_info-->", sdk_info)
    print("表单数--> ", len(sdk_info))

    for i in range(0, len(sdk_info)):
        db = pool.connection()
        cursor = db.cursor()
        sql = 'SELECT `审批编号` FROM CMDB.form;'

        cursor.execute(sql)
        business = cursor.fetchall()

        cursor.close()
        db.close()
        # 将获取的数据放在字典中
        business_set = {x[0] for x in business}
        business_id = sdk_info[i].get("business_id")
        status = sdk_info[i].get("status")
        departmentName = dingding.getDepartmentInfo(sdk_info[i].get("originator_dept_id"))

        # 如果该条请求没有被处理并且审批通过
        if business_id not in business_set and status == "COMPLETED":
            print("开始处理表单")

            # 开始处理该表单，先存入form表中，已处理过；防止异常表单被循环处理
            db = pool.connection()
            cursor = db.cursor()

            sql = f'INSERT INTO CMDB.form (`审批编号`) VALUES("{business_id}");'

            cursor.execute(sql)
            db.commit()

            cursor.close()
            db.close()

            # 获取该表单信息和发起人的userid
            infos = sdk_info[i]["form_component_values"]
            back_user = sdk_info[i].get("originator_userid")
            print("infos ==> ", infos)

            # 遍历钉钉表单信息，将每一条工单信息转换成字典
            formInfo = {}
            for info in infos:
                formInfo[info["name"]] = info["value"]
            print("formInfo --> ", formInfo)
            print()
            print(formInfo.keys())
            print(formInfo.values())
            print()

            # 处理新建服务器表单
            if formInfo["资源类型"] == "物理机" and formInfo["申请类型"] == "新建":
                print("处理新建物理机")
                formInfo["开始时间"] = eval(formInfo['["开始时间","结束时间"]'])[0]
                formInfo["结束时间"] = eval(formInfo['["开始时间","结束时间"]'])[1]
                starttime = datetime.datetime.strptime(formInfo["开始时间"], "%Y-%m-%d").date()
                endtime = datetime.datetime.strptime(formInfo["结束时间"], "%Y-%m-%d").date()

                # 计算时间差，如果超过180天，则申请失败
                Days = (endtime - starttime).days
                print("Days->", Days)
                if Days >= 180:
                    msgtoApplicants = "申请服务器时间不能超过180天，请联系管理员！"
                    msgtoAdmin = str(formInfo["责任人"]) + "申请了服务器时间超过180天！"
                    dingding.post_message(back_user, msgtoApplicants)
                    dingding.post_message(FuZeRenid, msgtoAdmin)
                    continue

                addServerList = eval(formInfo["添加服务器"])
                netType = formInfo["网络类型"]
                # 开始根据 添加服务器  字段中的系统类型分配服务器
                # 分配服务器时，每次分配查询一台服务器
                for applyServer in addServerList:
                    osType = applyServer[0]["value"]

                    db = pool.connection()
                    cursor = db.cursor()
                    sql = f'SELECT `IP地址`, `序号` FROM CMDB.server WHERE `机房`="{netType}" AND `系统类型`="{osType}" AND `责任人`="已回收";'
                    cursor.execute(sql)
                    serverInfo = cursor.fetchone()

                    cursor.close()
                    db.close()

                    print("serverInfo-> ", serverInfo)
                    if serverInfo is None:
                        msgtoAdmin = formInfo["责任人"] + "申请了系统类型为 " + str(osType) + " 的服务器，申请失败，没有该系统类型的服务器"
                        msgtoApplicants = "暂时没有系统类型为" + str(osType) + " 的服务器，请联系管理员！"
                        dingding.post_message(back_user, msgtoApplicants)
                        dingding.post_message(FuZeRenid, msgtoAdmin)
                    else:
                        ipAddress, xuHao = serverInfo

                        # 将相关数据使用escape_string转义，防止特殊字符影响
                        formInfo["业务名称"] = escape_string(formInfo["业务名称"])
                        formInfo["结束时间"] = escape_string(formInfo["结束时间"])
                        formInfo["责任人"] = escape_string(formInfo["责任人"])
                        formInfo["所在部门"] = escape_string(formInfo["所在部门"])

                        # 开始调用函数 distributeServer 对服务器执行相关操作，对函数返回值执行对应的消息通知
                        flag = distributeServer(ipAddress)
                        if flag:
                            msgtoApplicants = "申请的服务器系统类型为 " + str(osType) + " 成功，IP地址为 " + str(
                                ipAddress) + " 密码为" + str(serverpasswd)
                            dingding.post_message(back_user, msgtoApplicants)
                        else:
                            msgtoApplicants = "申请的服务器系统类型为 " + str(osType) + " 成功，IP地址为 " + str(
                                ipAddress) + " 密码为" + str(serverpasswd) + "初始化密码异常，已通知管理员"
                            dingding.post_message(back_user, msgtoApplicants)
                            msgtoAdmin = formInfo["责任人"] + "申请IP地址为 " + str(ipAddress) + "修改密码失败"
                            dingding.post_message(FuZeRenid, msgtoAdmin)

                        # 更新数据库
                        sql = f'UPDATE CMDB.server SET `用途`="{formInfo["业务名称"]}",`到期时间`="{formInfo["结束时间"]}",' \
                              f'`责任人`="{formInfo["责任人"]}",`部门`="{departmentName}",`服务状态`="使用中" WHERE `序号`={xuHao};'
                        print(sql)

                        db = pool.connection()
                        cursor = db.cursor()
                        try:
                            cursor.execute(sql)
                            db.commit()
                            cursor.close()
                            db.close()

                            print("更新成功！")
                        except:
                            cursor.close()
                            db.close()
                            msgtoAdmin = "数据库 CMDB.server 中服务器IP地址为 " + str(ipAddress) + "更新失败!"
                            dingding.post_message(FuZeRenid, msgtoAdmin)

            # 处理续期表单
            elif formInfo["资源类型"] == "物理机" and formInfo["申请类型"] == "续期":
                print("处理物理机续期")
                # 检查该续期服务器IP是否存在，并且是回收，如果不存在或者已回收则申请失败
                ipAddress = escape_string(formInfo["IP地址"])
                zeRenRen = escape_string(formInfo["责任人"])

                db = pool.connection()
                cursor = db.cursor()
                sql = f'SELECT `序号` FROM CMDB.server WHERE `IP地址`="{ipAddress}" AND `责任人`="{zeRenRen}";'
                print(sql)
                cursor.execute(sql)
                serverKey = cursor.fetchone()
                cursor.close()
                db.close()

                # 如果该负责人申请续期的服务区去已回收，则需要重新申请
                if serverKey is None:
                    msgtoApplicants = "服务器IP地址为 " + str(ipAddress) + " 不存在或已回收，请重新申请服务器或联系管理员！"
                    msgtoAdmin = formInfo["责任人"] + "续期IP地址为 " + str(ipAddress) + " 的服务器不存在或已回收"
                    dingding.post_message(back_user, msgtoApplicants)
                    dingding.post_message(FuZeRenid, msgtoAdmin)
                    continue

                else:
                    xuHao = serverKey[0]

                    formInfo["结束时间"] = escape_string(formInfo["结束时间"])

                    sql = f'UPDATE CMDB.server SET `到期时间`="{formInfo["结束时间"]}" WHERE `序号`="{xuHao}"'

                    db = pool.connection()
                    cursor = db.cursor()

                    try:
                        cursor.execute(sql)
                        db.commit()
                        cursor.close()
                        db.close()
                        msgtoApplicants = "服务器IP地址为 " + str(ipAddress) + " 续期成功！"
                        dingding.post_message(back_user, msgtoApplicants)

                    except:
                        cursor.close()
                        db.close()
                        msgtoApplicants = "服务器IP地址为 " + str(ipAddress) + " 续期失败，请联系管理员！"
                        msgtoAdmin = formInfo["责任人"] + "续期IP地址为 " + str(ipAddress) + " 的服务器失败，SQL语句异常"
                        dingding.post_message(back_user, msgtoApplicants)
                        dingding.post_message(FuZeRenid, msgtoAdmin)

            # 处理虚拟机表单
            elif formInfo["资源类型"] == "虚拟机":
                print("处理虚拟机")
                msgtoApplicants = '申请虚拟机请联系管理员！'
                msgtoAdmin = str(formInfo["责任人"]) + '申请了类型为 ' + str(formInfo["选择虚拟机类型"]) + ' 的虚拟机'
                dingding.post_message(back_user, msgtoApplicants)
                dingding.post_message(FuZeRenid, msgtoAdmin)

                # # 对虚拟机进行处理时，根据发起者申请的虚拟机类型选择虚拟机模板进行克隆
                # # 调整克隆虚拟机的大小在 Clonevm.py 中的参数cup_num、memory等
                # if formInfo["选择虚拟机类型"] == 'windows2016':
                #     vmTemplateName = "win2016基础环境"
                # elif formInfo["选择虚拟机类型"] == 'Centos':
                #     vmTemplateName = "Centos"
                # else:
                #     msgtoApplicants = "无法创建该类型的虚拟机，请联系管理员！"
                #     msgtoAdmin = formInfo["责任人"] + "申请了类型为 " + str(formInfo["选择虚拟机类型"]) + "的虚拟机！"
                #     dingding.post_message(back_user, msgtoApplicants)
                #     dingding.post_message(FuZeRenid, msgtoAdmin)
                #     continue
                #
                # # 开始克隆虚拟机
                # vmName = str(formInfo["责任人"]) + "_" + str(formInfo["业务名称"])
                # from script.Clonevm import cloneJob
                #
                # print(vmTemplateName)
                # data = cloneJob(template_name=vmTemplateName, vm_name=vmName)
                # if data["result"] == False:
                #     msgtoApplicants = '申请虚拟机失败，请联系管理员！'
                #     msgtoAdmin = str(formInfo["责任人"]) + '申请虚拟机' + str(formInfo["选择虚拟机类型"]) + ' ' + str(data["message"])
                #     dingding.post_message(back_user, msgtoApplicants)
                #     dingding.post_message(FuZeRenid, msgtoAdmin)
                #     print("data-->", data)
                #     continue
                #
                # for info in formInfo:
                #     formInfo[info] = escape_string(formInfo[info])
                #
                # # 获取虚拟机的id，返回类型未列表类型
                # vms = client.vcenter.VM.list(client.vcenter.VM.FilterSpec(names={vmName}))[0]
                # vmid = vms.vm
                #
                # sql = f'INSERT INTO CMDB.vmserver VALUES("虚拟机","{formInfo["选择虚拟机类型"]}",' \
                #       f'"{formInfo["业务名称"]}","{formInfo["结束时间"]}","{formInfo["责任人"]}","{formInfo["所在部门"]}","{vmName}","{vmid}")'
                # try:
                #     cursor.execute(sql)
                #     db.commit()
                #     msgtoApplicants = "申请的虚拟机名称为 " + str(vmName) + " ；密码为 " + str(serverpasswd)
                #     dingding.post_message(back_user, msgtoApplicants)
                #     print(msgtoApplicants)
                # except:
                #     msgtoAdmin = formInfo["责任人"] + "申请的虚拟机" + vmName + "信息更新数据库CMDB.vmserver失败！"
                #     dingding.post_message(FuZeRenid, msgtoAdmin)

            # 其余类型的表单暂不处理，通知管理员
            else:
                msgtoApplicants = "暂时没有该类型的申请处理，请联系管理员"
                dingding.post_message(back_user, msgtoApplicants)

                msgtoAdmin = formInfo["责任人"] + "申请了未添加请求"
                dingding.post_message(FuZeRenid, msgtoAdmin)
        else:
            print("该表单暂不处理！")


# 钉钉机器人信息
AGENT_ID = "xxxx"
appkey = "xxxx"
appsecret = "xxx-xxx-xxxxx"

# 在旧版钉钉中点击对应表单，processCode在url中
processCode = "xxx-xxx-xxx-xx-xxx-xxx"
# "dept_id": 865095136 研发中心

# 初始化钉钉类，同一条消息一天只能发送一次
dingding = DingDing(AGENT_ID=AGENT_ID, appkey=appkey, appsecret=appsecret, processCode=processCode)

# 处理钉钉表单任务，每小时执行一次
scheduler.add_job(func=corn_job, trigger='cron', hour='*/1', args=[FuZeRen], max_instances=6)
# 处理服务器到期提醒，每天执行一次
scheduler.add_job(func=serverinfo_job, trigger='cron', day='*/1', max_instances=2)
# scheduler.add_job(func=serverinfo_job, trigger='cron', minute='*/10', max_instances=2)
# # 处理虚拟机服务资产到期提醒，每天执行一次
# scheduler.add_job(func=vmserverinfo_job, trigger='cron', day='*/1')
# # 服务器免密测试，每天执行一次
# # scheduler.add_job(func=sshTestJob, trigger='cron', day='*/1')
