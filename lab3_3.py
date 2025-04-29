#!/usr/bin/env python
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from time import sleep, time
import os
import matplotlib.pyplot as plt

class SingleSwitchTopo(Topo):
    def build(self):
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1, cls=TCLink, bw=100, delay='50ms', max_queue_size=2000)

def parse_iperf_intervals(logfile):
    """解析iperf3日志，返回时间间隔和对应带宽列表"""
    timeline = []
    bandwidths = []
    try:
        with open(logfile, 'r') as f:
            for line in f:
                # 匹配示例: [  5]   3.00-4.00   sec  9.29 MBytes  77.9 Mbits/sec
                if 'sec' in line and 'Mbits' in line and 'sender' not in line:
                    parts = line.split()
                    
                    # 提取时间间隔（取结束时间）
                    time_str = parts[2].split('-')[1]
                    timeline.append(float(time_str))
                    
                    # 提取带宽值和单位
                    bw_value = float(parts[6])
                    bw_unit = parts[7]
                    
                    # 转换为Mbps
                    if bw_unit == 'Gbits/sec':
                        bw_value *= 1000
                    elif bw_unit == 'Kbits/sec':
                        bw_value /= 1000
                    bandwidths.append(bw_value)
        
        return timeline, bandwidths
    except Exception as e:
        print(f"[ERROR] 解析日志失败 {logfile}: {str(e)}")
        return [], []

def plot_bandwidth(t1, b1, t2, b2):
    """绘制双流带宽曲线"""
    plt.figure(figsize=(12, 6))
    
    # 绘制流1曲线（蓝色）
    if t1 and b1:
        plt.plot(t1, b1, label='Flow 1 (h1->h3)', color='blue', marker='o')
    
    # 绘制流2曲线（绿色）
    if t2 and b2:
        plt.plot(t2, b2, label='Flow 2 (h2->h3)', color='green', marker='s')
    
    # 绘制理论限制线
    max_time = max(t1[-1] if t1 else 0, t2[-1] if t2 else 0)
    plt.plot([0, max_time], [100, 100], 'r--', label='100Mbps Limit')
    
    plt.xlabel('Time (seconds)')
    plt.ylabel('Bandwidth (Mbps)')
    plt.title('TCP Cubic Bandwidth Allocation')
    plt.legend()
    plt.grid(True)
    plt.savefig('tcp_flows.png')
    plt.show()

def main():
    os.system('sudo mn -c 2>/dev/null')
    os.system('sudo pkill -9 -f "iperf3" 2>/dev/null')

    net = Mininet(topo=SingleSwitchTopo(), link=TCLink)
    try:
        net.start()
        print("[STATUS] 拓扑已启动")

        h3 = net.get('h3')
        h1 = net.get('h1')
        h2 = net.get('h2')
        
        # 清理环境
        h3.cmd('killall -9 iperf3 2> /dev/null')

        # 启动服务端
        print("[STATUS] 启动iperf服务端...")
        h3.cmd('iperf3 -s -p 5201 -4 --interval 1 &')  # 每秒报告一次
        h3.cmd('iperf3 -s -p 5202 -4 --interval 1 &')
        sleep(2)

        # 启动客户端
        print("[STATUS] 启动iperf客户端...")
        h1.cmd('iperf3 -c 10.0.0.3 -p 5201 -t 10 --interval 1 --logfile /tmp/client1.log &')
        h2.cmd('iperf3 -c 10.0.0.3 -p 5202 -t 10 --interval 1 --logfile /tmp/client2.log &')
        
        # 等待测试完成
        sleep(12)

        # 解析日志数据
        t1, b1 = parse_iperf_intervals('/tmp/client1.log')
        t2, b2 = parse_iperf_intervals('/tmp/client2.log')
        
        # 打印统计信息
        print(f"\nFlow1 平均带宽: {sum(b1)/len(b1):.2f} Mbps")
        print(f"Flow2 平均带宽: {sum(b2)/len(b2):.2f} Mbps")
        
        # 生成可视化图表
        plot_bandwidth(t1, b1, t2, b2)

    except Exception as e:
        print(f"[ERROR] 发生异常: {str(e)}")
    finally:
        net.stop()

if __name__ == '__main__':
    main()