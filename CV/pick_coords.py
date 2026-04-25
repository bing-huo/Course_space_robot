import cv2
import numpy as np
import torch
import matplotlib.pyplot as plt
import os

# ==========================================
# 1. 核心追踪器 (集成三帧启动与物理校准)
# ==========================================
class PrecisionTrackerV14:
    def __init__(self, H_matrix, max_lost=30):
        self.H = H_matrix
        self.last_t = None
        self.init_buffer = [] 
        self.vel_inited = False
        
        # 卡尔曼滤波器 [X, Y, Vx, Vy]
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        self.kf.transitionMatrix = np.eye(4, dtype=np.float32)
        
        # 测量噪声 R=6.0：强力平滑，消除由于画面分辨率产生的微小像素跳变
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.001
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 6.0 
        self.kf.errorCovPost = np.eye(4, dtype=np.float32)

    def pixel_to_world(self, u, v):
        src = np.array([[[float(u), float(v)]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(src, self.H)
        return dst[0][0][0], dst[0][0][1]

    def update(self, best_box, timestamp):
        if best_box is not None:
            # 追踪底边中点 (u, v_bottom) 以消除透视高度误差
            u, v_bot = (best_box[0] + best_box[2]) / 2, best_box[3]
            curr_x, curr_y = self.pixel_to_world(u, v_bot)
        else:
            curr_x, curr_y = None, None

        if self.last_t is None:
            if curr_x is None: return None
            self.last_t = timestamp
            self.init_buffer.append((curr_x, curr_y, timestamp))
            return curr_x, curr_y, 0.0, 0.0, "INIT"

        dt = timestamp - self.last_t
        self.last_t = timestamp
        
        # 三帧平滑启动：利用物理位移直接注入初始速度
        if not self.vel_inited and curr_x is not None:
            self.init_buffer.append((curr_x, curr_y, timestamp))
            if len(self.init_buffer) >= 3:
                p_s, p_e = self.init_buffer[0], self.init_buffer[-1]
                v_x = (p_e[0] - p_s[0]) / (p_e[2] - p_s[2])
                v_y = (p_e[1] - p_s[1]) / (p_e[2] - p_s[2])
                self.kf.statePost = np.array([[curr_x], [curr_y], [v_x], [v_y]], np.float32)
                self.vel_inited = True
            return curr_x, curr_y, 0.0, 0.0, "SYNC"

        self.kf.transitionMatrix[0, 2] = dt
        self.kf.transitionMatrix[1, 3] = dt
        if best_box is not None:
            meas = np.array([[np.float32(curr_x)], [np.float32(curr_y)]])
            self.kf.predict()
            state = self.kf.correct(meas)
            status = "TRACKING"
        else:
            state = self.kf.predict()
            status = "PREDICTING"

        x, y, vx, vy = state.flatten()
        return x, y, vx, vy, status

# ==========================================
# 2. 增强型验收报表 (全相位标注 + 百分比误差)
# ==========================================
def save_final_acceptance_report(h_t, h_x, h_y, h_v):
    if len(h_t) < 20: return
    
    t, x, y, v = np.array(h_t), np.array(h_x), np.array(h_y), np.array(h_v)
    TARGET_V = 21.0
    STABLE_TIME = 1.2 # 1.2秒定义为稳态起点
    
    # 计算百分比误差
    errors_pct = ((v - TARGET_V) / TARGET_V) * 100

    fig, axs = plt.subplots(2, 2, figsize=(15, 12))
    plt.subplots_adjust(hspace=0.35, wspace=0.25)

    def highlight_areas(ax):
        ax.axvspan(0, STABLE_TIME, color='red', alpha=0.08, label='Reaction Phase')
        ax.axvspan(STABLE_TIME, t[-1], color='green', alpha=0.08, label='Stable Phase')

    # 1. 2D 轨迹 (120x60cm 物理空间)
    axs[0,0].plot(x, y, 'purple', lw=2.5)
    axs[0,0].set_title('2D Trajectory (Calibration Corrected)', fontsize=12)
    axs[0,0].set_xlabel('Length X (cm)'); axs[0,0].set_ylabel('Width Y (cm)')
    axs[0,0].set_xlim(-10, 130); axs[0,0].set_ylim(-10, 70); axs[0,0].grid(True, ls=':')

    # 2. 线性位移图 (验证匀速性)
    axs[0,1].plot(t, x, 'dodgerblue', label='X-Pos (120cm direction)')
    axs[0,1].plot(t, y, 'coral', label='Y-Pos (60cm direction)')
    highlight_areas(axs[0,1])
    axs[0,1].set_title('Linear Displacement Analysis', fontsize=12)
    axs[0,1].set_xlabel('Time (s)'); axs[0,1].set_ylabel('Position (cm)')
    axs[0,1].legend(); axs[0,1].grid(True, alpha=0.3)

    # 3. 速度性能 (带 15% 达标带)
    axs[1,0].plot(t, v, 'b', lw=2)
    axs[1,0].axhline(y=TARGET_V, color='red', ls='--', label='Target 21cm/s')
    highlight_areas(axs[1,0])
    axs[1,0].fill_between(t, TARGET_V*0.85, TARGET_V*1.15, color='gray', alpha=0.2, label='15% Error Band')
    axs[1,0].set_title('Velocity Stability Analysis', fontsize=12)
    axs[1,0].set_ylabel('Speed (cm/s)'); axs[1,0].set_ylim(0, 35); axs[1,0].legend(loc='lower right'); axs[1,0].grid(True, alpha=0.3)

    # 4. 百分比误差图 (验收关键指标)
    axs[1,1].plot(t, errors_pct, 'orange', lw=1.5)
    axs[1,1].axhline(y=0, color='k')
    axs[1,1].axhline(y=15, color='red', ls=':', label='+15% Limit')
    axs[1,1].axhline(y=-15, color='red', ls=':', label='-15% Limit')
    highlight_areas(axs[1,1])
    axs[1,1].set_title('Real-time Velocity Error (%)', fontsize=12)
    axs[1,1].set_xlabel('Time (s)'); axs[1,1].set_ylabel('Error Percentage (%)')
    axs[1,1].set_ylim(-35, 35); axs[1,1].legend(); axs[1,1].grid(True)

    plt.savefig('acceptance_report_final_v14.png', dpi=300)
    print("验收报告已生成：acceptance_report_final_v14.png")
    plt.show()

# ==========================================
# 3. 主程序循环
# ==========================================
if __name__ == "__main__":
    MANUAL_FPS = 60.0
    VEL_SCALE = 0.86 # 最终比例微调
    
    # 按照用户提供的像素坐标顺序进行物理映射
    # [471, 235] -> [0, 0]
    # [3473, 195] -> [120, 0]
    # [3602, 1177] -> [120, 60]
    # [390, 1236] -> [0, 60]
    pts_px_raw = np.array([[471, 235], [3473, 195], [3602, 1177], [390, 1236]], dtype=np.int32)
    pts_wd = np.float32([[0, 0], [120, 0], [120, 60], [0, 60]]) 
    H = cv2.getPerspectiveTransform(pts_px_raw.astype(np.float32), pts_wd)

    print("--- 正在启动：空间机器人捕获性能验收系统 V14 ---")
    model = torch.hub.load('ultralytics/yolov5', 'custom', path='best.pt')
    cap = cv2.VideoCapture("test_video.mp4")
    w, h = int(cap.get(3)), int(cap.get(4))
    out = cv2.VideoWriter('acceptance_v14_demo.mp4', cv2.VideoWriter_fourcc(*'mp4v'), MANUAL_FPS, (w, h))
    
    tracker = PrecisionTrackerV14(H)
    h_t, h_x, h_y, h_v = [], [], [], []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        
        # --- 强调标定区域 (视频覆盖层渲染) ---
        overlay = frame.copy()
        cv2.fillPoly(overlay, [pts_px_raw], (255, 150, 0)) # 蓝色高亮
        cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
        cv2.polylines(frame, [pts_px_raw], True, (255, 255, 0), 3)

        curr_t = len(h_t) / MANUAL_FPS
        results = model(frame)
        pd = results.xyxy[0].cpu().numpy()
        best_box = pd[0] if len(pd) > 0 else None
        
        res = tracker.update(best_box, curr_t)
        
        if res is not None:
            X, Y, Vx, Vy, status = res
            V_abs = np.sqrt(Vx**2 + Vy**2) * VEL_SCALE
            h_t.append(curr_t); h_x.append(X); h_y.append(Y); h_v.append(V_abs)
            
            if best_box is not None:
                x1, y1, x2, y2 = map(int, best_box[:4])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"Velocity: {V_abs:.1f} cm/s", (50, 80), 0, 1.2, (0, 255, 0), 3)

        out.write(frame)
        cv2.imshow("Space Capture Acceptance V14", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release(); out.release(); cv2.destroyAllWindows()
    save_final_acceptance_report(h_t, h_x, h_y, h_v)