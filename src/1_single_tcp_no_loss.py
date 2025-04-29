#!/usr/bin/env python

# ---------------------------- 模块导入 ----------------------------
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.util import quietRun
from time import sleep, time
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

# -------------------------- 网络拓扑定义 --------------------------
class SingleSwitchTopo(Topo):
    """自定义网络拓扑(单交换机三主机结构)"""
    def build(self):
        """
        构建网络拓扑：
        - h1, h2: 普通主机(发送端)
        - h3: 服务器主机(接收端)
        - s1: 核心交换机
        - 链路特性: h3连接的链路设置带宽限制和延迟模拟网络瓶颈
        """
        h1 = self.addHost('h1')   # 添加发送端主机h1
        h2 = self.addHost('h2')   # 添加备用主机h2
        h3 = self.addHost('h3')   # 添加接收端主机h3
        s1 = self.addSwitch('s1') # 添加Open vSwitch交换机
        # 配置链路参数（h3为瓶颈节点）
        self.addLink(h1, s1)     # h1-s1普通链路
        self.addLink(h2, s1)     # h2-s1普通链路
        self.addLink(h3, s1,     # h3-s1受限链路
                    cls=TCLink,
                    bw=100,        # 带宽100Mbps
                    delay='50ms',  # 传播延迟50ms
                    max_queue_size=2000)  # 最大队列长度2000

# -------------------------- 主程序逻辑 --------------------------
def main():

    # ---------------------- 实验环境初始化 ----------------------
    os.system('sudo mn -c 2>/dev/null')         # 清理残留的Mininet进程
    os.system('sudo pkill -f "ss -tin" 2>/dev/null')  # 终止旧的监控进程
    os.system('sudo rm -f /tmp/cwnd.log 2>/dev/null') # 删除旧日志文件

    # -------------------- 网络拓扑实例化 --------------------
    topo = SingleSwitchTopo()  # 创建自定义拓扑对象
    net = Mininet(topo=topo, link=TCLink)  # 实例化Mininet网络

    try:
        # ------------------ 启动网络拓扑 ------------------
        net.start()  # 启动所有网络组件
        print("[DEBUG] 拓扑已启动")

        # ---------------- 配置交换机流表 ---------------
        s1 = net.get('s1')
        quietRun('ovs-ofctl add-flow s1 actions=normal')  # 设置开放流表
        print(f"[DEBUG] 交换机流表配置完成:\n{s1.cmd('ovs-ofctl dump-flows s1')}")

        # ---------------- 启动服务端程序 ----------------
        h3 = net.get('h3')
        h3.cmd('killall iperf3 2> /dev/null')   # 终止可能存在的旧进程
        h3.cmd('iperf3 -s --port 5201 &')       # 后台启动iperf3服务端
        print("[DEBUG] iperf3服务端已启动")

        # ------------ 配置拥塞窗口监控程序 ------------
        h1 = net.get('h1')
        cwnd_log = '/tmp/cwnd.log'  # 日志文件路径

        # 监控命令分解说明：
        # 1. while循环持续运行监控进程
        # 2. 获取精确到毫秒的时间戳
        # 3. 获取控制连接的端口号（用于过滤干扰）
        # 4. 提取数据连接的所有cwnd值(多个流用逗号分隔)
        # 5. 100ms采样间隔写入日志文件
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
        h1.cmd(monitor_cmd)  # 在h1节点上执行监控命令
        print("[DEBUG] cwnd监控已启动")
        sleep(2)  # 等待监控程序稳定运行

        # ------------------- 执行测试 -------------------
        start_time = time()  # 记录实验开始时间
        # 启动iperf客户端进行测试（关键参数说明）：
        # -c 指定服务器地址
        # -t 指定测试时长5秒 
        # -C 使用TCP Cubic算法
        # --port 指定使用5201端口
        iperf_output = h1.cmd('iperf3 -c 10.0.0.3 -t 5 -C cubic --port 5201')
        end_time = start_time + 5  # 计算理论结束时间
        print(f"[DEBUG] iperf3客户端输出:\n{iperf_output}")

        # ----------------- 清理实验环境 -----------------
        h1.cmd("pkill -f 'ss -tin'")  # 停止监控进程
        net.stop()  # 关闭网络

        # ----------------- 数据处理阶段 -----------------
        if os.path.exists(cwnd_log) and os.path.getsize(cwnd_log) > 0:
            # 读取原始日志文件（最多支持10个并行流）
            df = pd.read_csv(
                cwnd_log,
                header=None,
                sep=',',
                on_bad_lines='warn',  # 忽略格式错误行
                engine='python',      # 使用Python解析引擎
                names=['timestamp'] + [f'cwnd_{i}' for i in range(10)]
            )
            
             # --------- 数据清洗与转换 ---------
            def parse_row(row):
                """
                行数据处理函数：
                功能说明：
                1. 转换原始数据行为有效时间戳和最大cwnd值
                2. 过滤无效数据行
                3. 对多流情况取最大cwnd值
                """
                timestamp = row['timestamp']  # 提取时间戳
                cwnd_values = [v for v in row[1:] if not pd.isna(v)]  # 过滤空值
                # 仅处理包含2个及以上有效cwnd值的行
                if len(cwnd_values) >= 2:
                    valid_values = [int(v) for v in cwnd_values]  # 类型转换
                    return pd.Series([timestamp, max(valid_values)])  # 取最大值逻辑
                return pd.Series([timestamp, np.nan])  # 返回无效标记

            # 应用数据处理函数
            df = df.apply(parse_row, axis=1)
            df.columns = ['timestamp', 'cwnd']  # 重命名列
            df = df.dropna(subset=['cwnd'])     # 移除非数值行
            
            # ------ 时间窗过滤与计算结果 ------
            if not df.empty:
                # 时间过滤：仅保留实验时间窗口内的数据
                df = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]
                df = df.sort_values('timestamp')  # 按时间排序
                df['time'] = df['timestamp'] - start_time  # 计算相对时间

                # 输出处理后的数据样本（调试用）
                print("\n[DEBUG] 处理后数据样本:")
                print(df.head(10))  # 前10条数据
                print(df.tail(10))  # 后10条数据

                # ---------------- 可视化结果 ----------------
                plt.figure(figsize=(12,6))
                plt.plot(df['time'].to_numpy(), df['cwnd'].to_numpy(), label='TCP Cubic', color='blue')
                plt.xlabel('Time (s)')
                plt.ylabel('Congestion Window (packets)')
                plt.title('TCP Cubic cwnd Dynamics')
                plt.legend()
                plt.grid(True)
                plt.savefig('figure/single_tcp_no_loss_test.png')
            else:
                print("[ERROR] 有效数据为空！")
        else:
            print("[ERROR] 无有效数据生成！")
    except Exception as e:
        print(f"[ERROR] 发生异常: {e}")
    finally:
        os.system('sudo mn -c 2>/dev/null')  # 最终环境清理

if __name__ == '__main__':
    main()