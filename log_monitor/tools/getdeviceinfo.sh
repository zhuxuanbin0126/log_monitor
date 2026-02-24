device_mac=$(cat /sys/class/net/wlan0/address)
hostname=$(sysctl kernel.hostname | awk -F "= " '{print $2}')
if [ $hostname != "buildroot" ]; then
    device_name=$(grep "DeviceName" /data/data/cn.huidu.lcd.player/files/config/DeviceInfoConfig.xml | awk -F ">" '{print $2}' | awk -F "<" '{print $1}')
    system_type="Android"
    device_System_Version=$(getprop ro.build.version.release)
else
    device_name=$(grep "name len=" /root/Box/config/dev_info.xml | awk -F ">" '{print $2}' | awk -F "<" '{print $1}')
    system_type="Linux"
    device_System_Version=$(uname -a | awk -F " " '{print $3}')
fi
echo "$device_mac $device_name $system_type $device_System_Version "
