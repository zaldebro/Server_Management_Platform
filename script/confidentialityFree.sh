[root@localhost confidentialityFree]# ll
total 16
-rw-r--r-- 1 root root  171 Aug 25 10:24 agent.service # 客户端 systemd 文件
-rw-r--r-- 1 root root 1214 Aug 25 10:29 agent.sh # 客户端 IP 变化推送脚本
-rw-r--r-- 1 root root 2834 Aug 25 11:15 confidentialityFree.sh # 免密脚本
-rw-r--r-- 1 root root   34 Aug 25 10:11 hosts # 存放主机 IP 密码等信息

[root@localhost myssh]# cat confidentialityFree.sh
#!/bin/bash

# 是否安装非交互输入工具 expect 和 ssh
[[ -f /usr/bin/expect ]] || { yum install expect -y; }
[[ -f /usr/bin/ssh ]] || { yum install openssh-server openssh-clients -y; }

# 执行免密函数
autoSshCopyId(){
  password=$1
  hostIp=$2
  expect -c "set timeout -1;
  spawn ssh-copy-id -i -f ${hostIp};
  expect {
  *(yes/no)* {send -- yes\r;exp_continue;}
  *assword:* {send -- ${password}\r;exp_continue;}
  eof {exit 0;}
  }";
}

# 推送客户端脚本
pushScripts(){
  hostIp=$1
  serverip=`hostname -I | awk '{print $1}'`
  agent_path="/usr/local/monitor"
  ssh root@${hostIp} "mkdir /usr/local/monitor"
  scp ./agent.sh  ${hostIp}:${agent_path}/agent.sh
  scp ./agent.service ${hostIp}:/etc/systemd/system/agent.service
  ssh root@${hostIp} "echo ${serverip} > ${agent_path}/serverip"
  ssh root@${hostIp} "chmod +x ${agent_path}/agent.sh"
  ssh root@${hostIp} "systemctl daemon-reload && systemctl enable --now agent"
  echo -e "【\033[34m成功！\033[0m】"
}

confidentialityFreetoAll(){
  # 执行本次免密任务时，清除上次免密失败的主机清单
  [[ -f ./unreachableHosts ]] && rm -f ./unreachableHosts

  # 设置分隔符，否则for循环读取出的数据不符合预期
  IFS=$'\n\n'
  # 使用MySQL数据库信息
  # for hostInfo in `mysql --skip-column-names -uroot -p'xxxxxx' -e "select IP地址,密码 from CMDB.tablename;"`; do

  # 使用文件信息
  for hostInfo in $(<./hosts);do    #***主机 ip 文件，一行一个***#
    hostIp=`echo ${hostInfo} | awk '{print $1}'`
    password=`echo ${hostInfo} | awk '{print $2}'`
    ssh-keygen -F ${hostIp} && ssh-keygen -R ${hostIp}

    autoSshCopyId ${password} ${hostIp}

    res=`ssh root@${hostIp} -o PreferredAuthentications=publickey -o StrictHostKeyChecking=no "date" | wc -l`

    if [[ ${res} -eq 0 ]];then
      ssh-keygen -R ${hostIp}
      echo ${hostIp} >> ./unreachableHosts
    else

      pushScripts ${hostIp}

    fi
  done

  # 返回相关执行状态信息
  if [[ -f ./unreachableHosts ]];then
    echo "免密失败主机[./unreachableHosts]："  && cat ./unreachableHosts
  else
    echo "免密成功，没有免密失败主机！"
  fi
}

confidentialityFreetoOne(){
  read -p "请输入IP> " hostIp
  read -p "请输入密码> " password
  echo "主机IP为：${hostIp}  密码为：${password}"

  autoSshCopyId ${password} ${hostIp}

  res=`ssh root@${hostIp} -o PreferredAuthentications=publickey -o StrictHostKeyChecking=no "date" | wc -l`

  if [[ ${res} -eq 0 ]];then
    ssh-keygen -R ${hostIp}
    echo -e "【\033[34m失败！\033[0m】"
  else
    pushScripts ${hostIp}
  fi
}

echo "     选项
1 对所有主机执行免密操作
2 对指定主机执行免密操作
"
read -p "请输入选择 [ 1 or 2 ] > " choice

case ${choice} in
  1)
    confidentialityFreetoAll
  ;;

  2)
    confidentialityFreetoOne
  ;;

  *)
  echo "输入选项不存在，请重试！"
esac
