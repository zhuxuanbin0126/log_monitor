#! /bin/sh
#zrh build in 2025_08_26
PATH1=/root/Box/project
PATH2=/data

if [ -d "$PATH1" ];then
	SAVE_PATH=$PATH1
	system_name="linux"
elif [ -d "$PATH2" ];then
	SAVE_PATH=$PATH2
	system_name="android"
else
	echo "non-existent save path"
	exit
fi

ls $SAVE_PATH/swich_counter_flag > /dev/null || exit

current_time=`date +"%Y-%m-%d-%H-%M-%S"`
if [ $system_name == "android" ];then
	ls $SAVE_PATH/logcat > /dev/null ||  mkdir -p $SAVE_PATH/logcat
	logcat > $SAVE_PATH/logcat/logcat_$current_time.txt &
fi

echo "[boot_counter] checkout swich_counter_flag" > /dev/kmsg
if [ $system_name == "android" ];then
	log "[boot_counter] checkout swich_counter_flag"
fi
sleep 20
echo "[boot_counter] sleep success $current_time" > /dev/kmsg
if [ $system_name == "android" ];then
	log "[boot_counter] sleep success $current_time"
fi
sys_uptime=`cat /proc/uptime | busybox awk '{ print $1}'`
app_run=`ps -A | grep lcd | wc -l`
link_speed=`cat /sys/class/net/eth0/speed`
link_mode=`cat /sys/class/net/eth0/duplex`
carrier=`cat /sys/class/net/eth0/carrier`
device_ip=`ifconfig eth0 | grep 'inet addr:' | cut -d: -f2 | busybox awk '{ print $1}'`

ls $SAVE_PATH/swich_counter.csv > /dev/null || echo "BootTime,Uptime,AppSize,IP,Carrier,LinkSpeed,LinkMode" > $SAVE_PATH/swich_counter.csv
echo "${current_time},${sys_uptime},${app_run},${device_ip},${carrier},${link_speed},${link_mode}" >> $SAVE_PATH/swich_counter.csv
sync
echo "[boot_counter] write switch data success" > /dev/kmsg
if [ $system_name == "android" ];then
	log "[boot_counter] write switch data success"
fi

sync
gateway_ip=`ifconfig eth0 | grep "inet addr" | cut -d: -f3 | busybox awk '{ print $1; }' | busybox awk '{ gsub("255","1"); print }'`
echo "[boot_counter] gateway_ip is $gateway_ip" > /dev/kmsg
ping_local=`ping -c 4 -t 1 -W 2 $gateway_ip | grep "bytes from" | wc -l`
echo "[boot_counter] ping_local is $ping_local" > /dev/kmsg
now_device_ip=`ifconfig eth0 | grep 'inet addr:' | cut -d: -f2 | busybox awk '{ print $1}'`
echo "[boot_counter] now_device_ip is $now_device_ip" > /dev/kmsg
#ping次数统计
ping_huidu_network_times=0

# 循环4次，每次执行单次Ping
for i in 1 2 3 4; do
    # 单次Ping（-c 1），超时2秒（timeout 2）
    ping_network=`timeout 2 ping -c 1 dms.huidu.cn`
    # 检查退出状态码：0=成功，非0=失败
    if [ $? -eq 0 ]; then
		echo "[boot_counter] ping $i dms.huidu.cn success" > /dev/kmsg
        let ping_huidu_network_times++  # 成功则计数器+1
	else
		#失败后将内容输出到串口以及文件中
		echo "[boot_counter] ping $i dms.huidu.cn failed" > /dev/kmsg
		ls $SAVE_PATH/ping > /dev/null || mkdir -p $SAVE_PATH/ping
		ls  $SAVE_PATH/ping/ping_huidu_$current_time.txt > /dev/null || touch $SAVE_PATH/ping/ping_huidu_$current_time.txt
		echo "$ping_network" >> $SAVE_PATH/ping/ping_huidu_$current_time.txt
		echo "$now_device_ip" >> $SAVE_PATH/ping/ping_huidu_$current_time.txt
    fi
done

ping_baidu_network_times=0

# 循环4次，每次执行单次Ping
for i in 1 2 3 4; do
    # 单次Ping（-c 1），超时2秒（timeout 2）
    ping_network=`timeout 2 ping -c 1 www.baidu.com`
    # 检查退出状态码：0=成功，非0=失败
    if [ $? -eq 0 ]; then
		echo "[boot_counter] ping $i www.baidu.com success" > /dev/kmsg
        let ping_baidu_network_times++  # 成功则计数器+1
	else
		#失败后将内容输出到串口以及文件中
		echo "[boot_counter] ping $i www.baidu.com failed" > /dev/kmsg
		ls $SAVE_PATH/ping > /dev/null || mkdir -p $SAVE_PATH/ping
		ls  $SAVE_PATH/ping/ping_baidu_$current_time.txt > /dev/null || touch $SAVE_PATH/ping/ping_baidu_$current_time.txt
		echo "$ping_network" >> $SAVE_PATH/ping/ping_baidu_$current_time.txt
		echo "$now_device_ip" >> $SAVE_PATH/ping/ping_baidu_$current_time.txt
    fi
	
done

ls $SAVE_PATH/network_counter.csv > /dev/null || echo "BootTime,Uptime,AppSize,IP,Carrier,LinkSpeed,LinkMode,PingLocal,PingHuiduNetwork,PingBaiduNetwork" > $SAVE_PATH/network_counter.csv
echo "${current_time},${sys_uptime},${app_run},${device_ip},${carrier},${link_speed},${link_mode},${ping_local},${ping_huidu_network_times},${ping_baidu_network_times}" >> $SAVE_PATH/network_counter.csv
sync
echo "[boot_counter] write network data success" > /dev/kmsg
if [ $system_name == "android" ];then
	log "[boot_counter] write network data success"
fi
exit
