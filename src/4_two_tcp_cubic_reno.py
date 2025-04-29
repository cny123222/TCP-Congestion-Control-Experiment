#!/usr/bin/env python
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from time import sleep
import os
import matplotlib.pyplot as plt

class SingleSwitchTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1, cls=TCLink, bw=100, delay='50ms', max_queue_size=150)

def parse_iperf_intervals(logfile):
    timeline, bandwidths = [], []
    try:
        with open(logfile, 'r') as f:
            for line in f:
                if 'sec' in line and 'Mbits/sec' in line and 'sender' not in line:
                    parts = line.split()
                    time_end = float(parts[2].split('-')[1]) 
                    bw_val = float(parts[6]) 
                    unit = parts[7]

                    if unit == 'Gbits/sec':
                        bw_val *= 1000
                    elif unit == 'Kbits/sec':
                        bw_val /= 1000
                    
                    timeline.append(time_end)
                    bandwidths.append(bw_val)
        return timeline, bandwidths
    except Exception as e:
        print(f"[ERROR] 解析失败: {str(e)}")
        return [], []

def plot_curves(t1, b1, t2, b2):
    plt.figure(figsize=(12,6))
    plt.plot(t1, b1, 'b-o', label='Cubic (h1->h3)', markersize=5)
    plt.plot(t2, b2, 'g--s', label='Reno (h2->h3)', markersize=5)
    plt.axhline(100, color='r', linestyle=':', label='100Mbps Limit')
    plt.xlabel('Time (seconds)')
    plt.ylabel('Bandwidth (Mbps)')
    plt.ylim(0, 105)
    plt.title('Cubic vs Reno Bandwidth Competition')
    plt.legend()
    plt.grid(True)
    plt.savefig('figure/two_tcp_cubic_reno_test.png')

def jains_fairness(avg1, avg2):
    """计算Jain公平性指数
    公式：
        fairness = (x1 + x2)^2 / (2*(x1^2 + x2^2))
    参数：
        avg1: 流1的平均带宽
        avg2: 流2的平均带宽
    返回：
        公平性指数(0.0~1.0)
    """
    if avg1 <= 0 or avg2 <= 0:
        return 0.0
    numerator = (avg1 + avg2) ** 2
    denominator = 2 * (avg1**2 + avg2**2)
    return numerator / denominator

def main():
    os.system('sudo mn -c 2>/dev/null')
    os.system('sudo pkill -9 -f iperf3')
    os.system('rm -f /tmp/client1.log /tmp/client2.log')

    net = Mininet(topo=SingleSwitchTopo(), link=TCLink)
    try:
        net.start()
        print("[STATUS] 拓扑启动成功")

        h3 = net.get('h3')
        h1 = net.get('h1')
        h2 = net.get('h2')

        h3.cmd('iperf3 -s -p 5201 -4 --interval 1 &')
        h3.cmd('iperf3 -s -p 5202 -4 --interval 1 &')
        sleep(2)

        h1.sendCmd('iperf3 -c 10.0.0.3 -p 5201 -t 15 -C cubic --interval 1 --logfile /tmp/client1.log')
        h2.sendCmd('iperf3 -c 10.0.0.3 -p 5202 -t 15 -C reno --interval 1 --logfile /tmp/client2.log')
        sleep(17)

        h1.waitOutput()
        h2.waitOutput()

        if not os.path.exists('/tmp/client1.log'):
            print("[ERROR] client1.log未生成")
        if not os.path.exists('/tmp/client2.log'):
            print("[ERROR] client2.log未生成")

        t1, b1 = parse_iperf_intervals('/tmp/client1.log')
        t2, b2 = parse_iperf_intervals('/tmp/client2.log')
        
        avg1 = sum(b1)/len(b1) if b1 else 0
        avg2 = sum(b2)/len(b2) if b2 else 0

        print(f"\n[结果] Flow1平均带宽: {avg1:.2f} Mbps")
        print(f"[结果] Flow2平均带宽: {avg2:.2f} Mbps")
        print(f"[结果] 总带宽: {avg1 + avg2:.2f} Mbps")
        print(f"[结果] 公平性指数: {jains_fairness(avg1, avg2):.4f}")

        plot_curves(t1, b1, t2, b2)

    finally:
        net.stop()

if __name__ == '__main__':
    main()