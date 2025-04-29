#!/usr/bin/env python
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from time import sleep
import os
import matplotlib.pyplot as plt

class CorrectedTopo(Topo):
    """确保所有流量经过100Mbps瓶颈链路"""
    def build(self):
        s1 = self.addSwitch('s1')
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        
        # 所有流量必须经过的带宽限制链路
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1, cls=TCLink, bw=100, delay='50ms')

def parse_iperf_intervals(logfile):
    """解析iperf3日志，提取时间和带宽序列"""
    timeline, bandwidths = [], []
    try:
        with open(logfile, 'r') as f:
            for line in f:
                if 'sec' in line and 'Mbits/sec' in line and 'sender' not in line:
                    parts = line.split()
                    time_end = float(parts[2].split('-')[1])  # 时间点（秒）
                    bw_val = float(parts[6])                   # 带宽数值
                    unit = parts[7]                            # 单位
                    
                    # 单位转换
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
    """绘制带宽变化曲线"""
    plt.figure(figsize=(12,6))
    plt.plot(t1, b1, 'b-o', label='Flow1 (h1->h3)', markersize=5)
    plt.plot(t2, b2, 'g--s', label='Flow2 (h2->h3)', markersize=5)
    plt.axhline(100, color='r', linestyle=':', label='100Mbps Limit')
    plt.xlabel('Time (seconds)')
    plt.ylabel('Bandwidth (Mbps)')
    plt.ylim(0, 105)
    plt.title('TCP Cubic Bandwidth Allocation')
    plt.legend()
    plt.grid(True)
    plt.savefig('tcp_flows.png')
    plt.show()

def jains_fairness(avg1, avg2):
    """正确计算公平性指数"""
    if avg1 <= 0 or avg2 <= 0:
        return 0.0
    numerator = (avg1 + avg2) ** 2
    denominator = 2 * (avg1**2 + avg2**2)
    return numerator / denominator

def main():
    os.system('sudo mn -c 2>/dev/null')
    os.system('sudo pkill -9 -f iperf3')

    net = Mininet(topo=CorrectedTopo(), link=TCLink)
    try:
        net.start()
        print("[STATUS] 拓扑启动成功")

        # 初始化主机
        h3 = net.get('h3')
        h1 = net.get('h1')
        h2 = net.get('h2')

        # 启动服务端（每秒报告一次）
        h3.cmd('iperf3 -s -p 5201 -4 --interval 1 &')
        h3.cmd('iperf3 -s -p 5202 -4 --interval 1 &')
        sleep(2)

        # 同步启动客户端
        h1.cmd('nohup iperf3 -c 10.0.0.3 -p 5201 -t 15 -C cubic --interval 1 --logfile /tmp/client1.log &')
        h2.cmd('nohup iperf3 -c 10.0.0.3 -p 5202 -t 15 -C cubic --interval 1 --logfile /tmp/client2.log &')
        
        # 等待测试完成
        sleep(20)

        # 解析日志数据
        t1, b1 = parse_iperf_intervals('/tmp/client1.log')
        t2, b2 = parse_iperf_intervals('/tmp/client2.log')
        
        # 计算平均带宽
        avg1 = sum(b1)/len(b1) if b1 else 0
        avg2 = sum(b2)/len(b2) if b2 else 0

        # 输出结果
        print(f"\n[结果] Flow1平均带宽: {avg1:.2f} Mbps")
        print(f"[结果] Flow2平均带宽: {avg2:.2f} Mbps")
        print(f"[结果] 总带宽: {avg1 + avg2:.2f} Mbps")
        print(f"[结果] 公平性指数: {jains_fairness(avg1, avg2):.4f}")

        # 生成图表
        plot_curves(t1, b1, t2, b2)

    finally:
        net.stop()

if __name__ == '__main__':
    main()