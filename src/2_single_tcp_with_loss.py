#!/usr/bin/env python
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.util import quietRun
from time import sleep, time
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

class SingleSwitchTopo(Topo):
    def build(self):
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1) 
        self.addLink(h2, s1) 
        self.addLink(h3, s1,
                    cls=TCLink,
                    bw=10,        # 带宽10Mbps
                    delay='100ms',  # 传播延迟100ms
                    max_queue_size=100)  # 最大队列长度100

def main():
    os.system('sudo mn -c 2>/dev/null')        
    os.system('sudo pkill -f "ss -tin" 2>/dev/null')  
    os.system('sudo rm -f /tmp/cwnd.log 2>/dev/null') 

    topo = SingleSwitchTopo()  
    net = Mininet(topo=topo, link=TCLink)  

    try:
        net.start()  
        print("[DEBUG] 拓扑已启动")

        s1 = net.get('s1')
        quietRun('ovs-ofctl add-flow s1 actions=normal') 
        print(f"[DEBUG] 交换机流表配置完成:\n{s1.cmd('ovs-ofctl dump-flows s1')}")

        h3 = net.get('h3')
        h3.cmd('killall iperf3 2> /dev/null')   
        h3.cmd('iperf3 -s --port 5201 &')      
        print("[DEBUG] iperf3服务端已启动")

        h1 = net.get('h1')
        # 初始添加0.1%丢包和50ms延迟
        h1.cmd('sudo tc qdisc add dev h1-eth0 root netem loss 0.1% delay 50ms')
        print("[DEBUG] 初始丢包规则已设置")

        cwnd_log = '/tmp/cwnd.log'  
        monitor_cmd = (
            "while true; do "
            "timestamp=$(date +%%s.%%3N 2>/dev/null) || echo 'NaN'; "
            "control_port=$(ss -tn state established dst 10.0.0.3 dport = 5201 | awk 'NR==2 {split($4, a, \":\"); print a[2]}') || echo ''; "
            "cwnd=$(ss -tin state established dst 10.0.0.3 dport = 5201 sport != \"$control_port\" | grep -oP 'cwnd:\\K\\d+' | paste -sd ',' -); "
            "[ -z \"$cwnd\" ] && cwnd='NaN'; "
            "echo \"$timestamp,$cwnd\"; "
            "sleep 0.1; "
            "done > %s &" % cwnd_log
        )
        h1.cmd(monitor_cmd)
        print("[DEBUG] cwnd监控已启动")
        sleep(2) 

        start_time = time()  
        # 延长实验时间到40秒
        iperf_output = h1.cmd('iperf3 -c 10.0.0.3 -t 40 -C cubic --port 5201')
        end_time = start_time + 40
        print(f"[DEBUG] iperf3客户端输出:\n{iperf_output}")

        # 清除丢包规则
        h1.cmd('sudo tc qdisc del dev h1-eth0 root')
        print("[DEBUG] 丢包规则已清除")

        h1.cmd("pkill -f 'ss -tin'")
        net.stop()

        if os.path.exists(cwnd_log) and os.path.getsize(cwnd_log) > 0:
            df = pd.read_csv(
                cwnd_log,
                header=None,
                sep=',',
                on_bad_lines='warn',
                engine='python', 
                names=['timestamp'] + [f'cwnd_{i}' for i in range(10)]
            )

            def parse_row(row):
                timestamp = row['timestamp']
                cwnd_values = [v for v in row[1:] if not pd.isna(v)]
                if len(cwnd_values) >= 2:
                    valid_values = [int(v) for v in cwnd_values]
                    return pd.Series([timestamp, max(valid_values)])
                return pd.Series([timestamp, np.nan])

            df = df.apply(parse_row, axis=1)
            df.columns = ['timestamp', 'cwnd']
            df = df.dropna(subset=['cwnd'])
            
            if not df.empty:
                df = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]
                df = df.sort_values('timestamp')
                df['time'] = df['timestamp'] - start_time  # 计算相对时间

                print("\n[DEBUG] 处理后数据样本:")
                print(df.head(10))
                print(df.tail(10))

                plt.figure(figsize=(15,6))
                plt.plot(df['time'].to_numpy(), df['cwnd'].to_numpy(), label='TCP Cubic', color='blue')
                plt.xlabel('Time (s)')
                plt.ylabel('Congestion Window (packets)')
                plt.title('TCP Cubic cwnd under 0.1% Loss (10Mbps, 100ms delay)')
                plt.legend()
                plt.grid(True)
                plt.savefig('figure/single_tcp_with_loss_test.png')
            else:
                print("[ERROR] 有效数据为空！")
        else:
            print("[ERROR] 无有效数据生成！")
    except Exception as e:
        print(f"[ERROR] 发生异常: {e}")
    finally:
        os.system('sudo mn -c 2>/dev/null')

if __name__ == '__main__':
    main()