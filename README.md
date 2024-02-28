# CMDB   （[前往我的个人博客系统](https://github.com/zaldebro/Personal_blog_system)）

实习期间开发CMDB资产管理系统，主要功能如下：

1、服务器资产管理页面，支持服务器资产的导入导出，支持字段的修改，支持资产自定义分组

2、对接钉钉服务器审批信息申请服务器地址，责任人等信息自动更新资产管理页面

3、服务器到期使用提醒，并对到期的机器做操作，比如关闭docker修改密码，通知的方式使用钉钉单聊的方式

4、允许在web界面对服务器执行shell命令；当资产中的主机IP地址发生变化时，自动更新IP地址等信息

本仓库中提供了对接钉钉部分和对服务器管理相关的代码

BP目录放置了对接钉钉部分的代码、script部分放置了相关脚本

下面是容器版本部署：
```shell
[root@localhost cmdb]# pwd
/cmdb
[root@localhost cmdb]# ll
total 101728
-rw-r--r-- 1 root root     1046 Aug 25 14:25 CMDBfile
-rw-r--r-- 1 root root 88751087 Aug 25 14:23 CMDB.zip
-rw-r--r-- 1 root root     2248 Aug 22 15:12 database.py
-rw-r--r-- 1 root root      490 Aug 22 14:54 Dockerins.sh
-rw-r--r-- 1 root root       50 Aug 22 14:47 MYSQLfile
-rw-r--r-- 1 root root      409 Aug 25 14:24 SHELLfile
drwxr-xr-x 4 root root       32 Aug 22 14:48 storage
-rw-r--r-- 1 root root      743 Aug 25 14:28 subassembly.yaml
-rw-r--r-- 1 root root      200 Aug 22 14:47 utf8mb4.cnf
-rw-r--r-- 1 root root 15381420 Aug 22 14:34 vsphere-automation-sdk-python-master.zip
-rw-r--r-- 1 root root     2513 Aug 22 14:48 webshell.py
# 启动MySQL、redis和提供主机免密操作的容器
[root@localhost cmdb]# docker-compose -f subassembly.yaml up -d
Creating cmdb_mysql_1 ... done
Creating cmdb_redis_1 ... done
Creating cmdb_shell_1 ... done
# 创建相关数据库
[root@localhost cmdb]# python3 database.py 
/usr/local/lib64/python3.6/site-packages/pymysql/_auth.py:8: CryptographyDeprecationWarning: Python 3.6 is no longer supported by the Python core team. Therefore, support for it is deprecated in cryptography. The next release of cryptography will remove support for Python 3.6.
  from cryptography.hazmat.backends import default_backend
ok
# 构建CMDB镜像并且启动
[root@localhost cmdb]# docker build -t cmdb:v1 --build-arg serverip=192.168.3.28 -f CMDBfile .
[root@localhost cmdb]# docker run -it -d -v /root/.ssh/:/root/.ssh/:rw -p 5000:5000 cmdb:v1
4e457144e431f44f26a4c0e7b2c1a8221a2a48b1f9c79458af14a3818b5c5239
[root@localhost cmdb]# docker ps
CONTAINER ID   IMAGE        COMMAND                  CREATED         STATUS         PORTS                                                  NAMES
4e457144e431   cmdb:v1      "python3 /usr/local/…"   2 seconds ago   Up 1 second    0.0.0.0:5000->5000/tcp, :::5000->5000/tcp              friendly_heyrovsky
86bc29cb7505   redis        "docker-entrypoint.s…"   6 minutes ago   Up 6 minutes   0.0.0.0:6379->6379/tcp, :::6379->6379/tcp              cmdb_redis_1
7d941bbe4597   myshell:v1   "python3 /usr/local/…"   6 minutes ago   Up 6 minutes   0.0.0.0:8765->8765/tcp, :::8765->8765/tcp              cmdb_shell_1
18b3fde8d3ac   mysql:v1     "docker-entrypoint.s…"   6 minutes ago   Up 6 minutes   0.0.0.0:3306->3306/tcp, :::3306->3306/tcp, 33060/tcp   cmdb_mysql_1
```
