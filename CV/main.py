import cv2
import numpy as np
import torch
import matplotlib.pyplot as plt
import os

# ==========================================
# 1. 核心追踪器 (动态变频卡尔曼 + 初速钳位)
# ==========================================
class TrackerProV20:
    def __init__(self, H_matrix, max_lost=30):
        self.H = H_matrix
        self.last_t = None
        self.init_buffer = [] 
        self.vel_inited = False
        
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        self.kf.transitionMatrix = np.eye(4, dtype=np.float32)
        
        # 默认使用高平滑状态 (后续会动态调整)
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.001
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 6.0 
        self.kf.errorCovPost = np.eye(4, dtype=np.float32)

    def pixel_to_world(self, u, v):
        src = np.array([[[float(u), float(v)]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(src, self.H)
        return dst[0][0][0], dst[0][0][1]

    def update(self, best_box, timestamp):
        # --- 动态卡尔曼参数调度 (Dynamic Filtering) ---
        if self.last_t is not None:
            if timestamp < 1.5:
                # 反应期：降低平滑度，快速收敛
                self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1.0
                self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.01
            else:
                # 稳定期：增强平滑度，完美匀速
                self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 6.0
                self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.001

        if best_box is not None:
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
        
        if not self.vel_inited and curr_x is not None:
            self.init_buffer.append((curr_x, curr_y, timestamp))
            if len(self.init_buffer) >= 3:
                p_s, p_e = self.init_buffer[0], self.init_buffer[-1]
                v_x = (p_e[0] - p_s[0]) / (p_e[2] - p_s[2])
                v_y = (p_e[1] - p_s[1]) / (p_e[2] - p_s[2])
                # 【初速钳位】坚决不允许开局算出过百的速度
                v_x = np.clip(v_x, -30.0, 30.0)
                v_y = np.clip(v_y, -30.0, 30.0)
                
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
# 2. 定制报表生成 (接入动态目标速度)
# ==========================================
def generate_fast_response_report(h_t, h_x, h_y, h_v, target_v):
    if len(h_t) < 20: return
    
    t, x, y, v = np.array(h_t), np.array(h_x), np.array(h_y), np.array(h_v)
    
    # 根据传入的目标速度计算误差
    errors_pct = ((v - target_v) / target_v) * 100

    # 报表时间轴划分
    T_REACTION_END = 1.5   
    T_EVAL_START = 3.0     
    T_EVAL_END = 11.0

    fig, axs = plt.subplots(2, 2, figsize=(15, 12))
    plt.subplots_adjust(hspace=0.35, wspace=0.25)

    def draw_advanced_zones(ax, t_max):
        # < 1.5s 极速收敛区
        ax.axvspan(0, T_REACTION_END, color='lightcoral', alpha=0.15, label='Fast Reaction (<1.5s)')
        # 3.0s - 11.0s 官方考核黄金区
        ax.axvspan(T_EVAL_START, min(t_max, T_EVAL_END), color='lightgreen', alpha=0.15, label='Evaluation Zone (3s-11s)')

    # 1. 轨迹图 (适应 180cm)
    axs[0,0].plot(x, y, 'purple', lw=2.5)
    axs[0,0].axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].axvline(x=180, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].set_title('2D Trajectory (180cm Calibration Box)', fontsize=12)
    axs[0,0].set_xlabel('Length X (cm)'); axs[0,0].set_ylabel('Width Y (cm)')
    axs[0,0].set_xlim(min(x)-10, max(200, max(x)+10)); axs[0,0].set_ylim(-10, 70); axs[0,0].grid(True, ls=':')

    # 2. 位移图
    axs[0,1].plot(t, x, 'dodgerblue', label='X-Pos (Moving Direction)')
    axs[0,1].plot(t, y, 'coral', label='Y-Pos (Lateral)')
    axs[0,1].axhline(y=0, color='gray', linestyle=':', label='Box Start (0cm)')
    axs[0,1].axhline(y=180, color='gray', linestyle=':', label='Box End (180cm)')
    draw_advanced_zones(axs[0,1], t[-1])
    axs[0,1].set_title('Linear Displacement Analysis', fontsize=12)
    axs[0,1].set_xlabel('Time (s)'); axs[0,1].set_ylabel('Position (cm)')
    
    handles, labels = axs[0,1].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[0,1].legend(by_label.values(), by_label.keys())
    axs[0,1].grid(True, alpha=0.3)

    # 3. 速度图 (动态更新基准线)
    axs[1,0].plot(t, v, 'b', lw=2)
    axs[1,0].axhline(y=target_v, color='red', ls='--', label=f'Target {target_v}cm/s')
    draw_advanced_zones(axs[1,0], t[-1])
    axs[1,0].fill_between(t, target_v*0.85, target_v*1.15, color='gray', alpha=0.2, label='15% Error Band')
    axs[1,0].set_title('Dynamic Velocity Tracking (Fast Converge)', fontsize=12)
    axs[1,0].set_ylabel('Speed (cm/s)')
    # 动态适应高度，最高显示目标速度的 1.6 倍
    axs[1,0].set_ylim(0, max(35, target_v * 1.6)) 
    
    handles, labels = axs[1,0].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[1,0].legend(by_label.values(), by_label.keys(), loc='lower right')
    axs[1,0].grid(True, alpha=0.3)

    # 4. 误差图
    axs[1,1].plot(t, errors_pct, 'orange', lw=1.5)
    axs[1,1].axhline(y=0, color='k')
    axs[1,1].axhline(y=15, color='red', ls=':', label='+15% Limit')
    axs[1,1].axhline(y=-15, color='red', ls=':', label='-15% Limit')
    draw_advanced_zones(axs[1,1], t[-1])
    axs[1,1].set_title(f'Real-time Velocity Error (%) - Target: {target_v}cm/s', fontsize=12)
    axs[1,1].set_xlabel('Time (s)'); axs[1,1].set_ylabel('Error Percentage (%)')
    axs[1,1].set_ylim(-35, 35) 
    
    handles, labels = axs[1,1].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[1,1].legend(by_label.values(), by_label.keys(), loc='lower right')
    axs[1,1].grid(True)

    plt.savefig('v20_target_selected_report.png', dpi=300)
    print("🎓 极速响应版报表已生成：v20_target_selected_report.png")
    plt.show()

# ==========================================
# 3. 鼠标交互标定
# ==========================================
pts_clicked = []
def click_event(event, x, y, flags, params):
    global pts_clicked
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(pts_clicked) < 4:
            pts_clicked.append([x, y])
            cv2.circle(frame_disp, (x, y), 6, (0, 0, 255), -1)
            if len(pts_clicked) > 1:
                cv2.line(frame_disp, tuple(pts_clicked[-2]), tuple(pts_clicked[-1]), (0, 255, 255), 2)
            if len(pts_clicked) == 4:
                cv2.line(frame_disp, tuple(pts_clicked[3]), tuple(pts_clicked[0]), (0, 255, 255), 2)
            cv2.imshow("Calibration - Click 180cm Box", frame_disp)

# ==========================================
# 4. 主程序运行
# ==========================================
if __name__ == "__main__":
    # --- 交互：获取目标速度 ---
    print("========================================")
    print("请在下方输入本次测试的小车【目标速度】(cm/s)")
    print("直接按回车键 (Enter) 则默认使用 21.0")
    print("========================================")
    target_input = input("> ")
    
    try:
        GLOBAL_TARGET_V = float(target_input) if target_input.strip() else 21.0
    except ValueError:
        print("⚠️ 输入无效，系统自动回退默认速度：21.0 cm/s")
        GLOBAL_TARGET_V = 21.0
        
    print(f"✅ 系统目标速度已锁定为: {GLOBAL_TARGET_V} cm/s\n")

    video_path = "test_video.mp4"
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("错误：打不开视频！")
        exit()

    ret, frame_first = cap.read()
    frame_disp = frame_first.copy()
    
    cv2.putText(frame_disp, "1. Click the Full 180cm Box (TL -> TR -> BR -> BL)", 
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(frame_disp, "2. Press SPACE to start.", 
                (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    
    cv2.imshow("Calibration - Click 180cm Box", frame_disp)
    cv2.setMouseCallback("Calibration - Click 180cm Box", click_event)
    
    print("请点击 180cm 的标定白框。")
    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' ') or key == 13: 
            if len(pts_clicked) == 4: break
    cv2.destroyWindow("Calibration - Click 180cm Box")
    
    pts_px = np.array(pts_clicked, dtype=np.float32)
    
    # 物理映射 180cm
    pts_wd = np.float32([[0, 0], [180, 0], [180, 60], [0, 60]]) 
    H = cv2.getPerspectiveTransform(pts_px, pts_wd)

    real_fps = cap.get(cv2.CAP_PROP_FPS)
    if real_fps == 0 or np.isnan(real_fps): real_fps = 30.0
    
    model = torch.hub.load('ultralytics/yolov5', 'custom', path='best.pt')
    w, h = int(cap.get(3)), int(cap.get(4))
    out = cv2.VideoWriter('v20_tracked_demo.mp4', cv2.VideoWriter_fourcc(*'mp4v'), real_fps, (w, h))
    
    tracker = TrackerProV20(H)
    h_t, h_x, h_y, h_v = [], [], [], []
    last_px_center = None 

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            overlay = frame.copy()
            cv2.fillPoly(overlay, [np.int32(pts_px)], (255, 100, 0))
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            cv2.polylines(frame, [np.int32(pts_px)], True, (255, 255, 0), 2)

            curr_t = len(h_t) / real_fps 
            results = model(frame)
            pd = results.xyxy[0].cpu().numpy()
            
            best_box = None
            if len(pd) > 0:
                if last_px_center is None:
                    best_box = pd[0]
                else:
                    min_dist = float('inf')
                    for box in pd:
                        cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
                        dist = np.hypot(cx - last_px_center[0], cy - last_px_center[1])
                        if dist < 150 and dist < min_dist:
                            min_dist = dist
                            best_box = box

            res = tracker.update(best_box, curr_t)
            
            if res is not None:
                X, Y, Vx, Vy, status = res
                V_abs = np.sqrt(Vx**2 + Vy**2)
                h_t.append(curr_t); h_x.append(X); h_y.append(Y); h_v.append(V_abs)
                
                if best_box is not None:
                    last_px_center = ((best_box[0]+best_box[2])/2, (best_box[1]+best_box[3])/2)
                    x1, y1, x2, y2 = map(int, best_box[:4])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                
                # --- 新增：实时在视频上渲染目标速度与实测速度 ---
                cv2.putText(frame, f"TARGET: {GLOBAL_TARGET_V:.1f} cm/s", (40, 40), 0, 1.0, (255, 255, 255), 2)
                cv2.putText(frame, f"VEL: {V_abs:.1f} cm/s", (40, 80), 0, 1.2, (0, 255, 0), 3)
                
                # UI 提示
                if curr_t < 1.5:
                    cv2.putText(frame, "FAST REACTION MODE", (40, 130), 0, 1.0, (0, 165, 255), 2)
                elif 3.0 <= curr_t <= 11.0:
                    cv2.putText(frame, "EVALUATION ZONE (3s-11s)", (40, 130), 0, 1.0, (0, 255, 0), 2)
                else:
                    cv2.putText(frame, "TRACKING...", (40, 130), 0, 1.0, (255, 255, 255), 2)

            out.write(frame)
            cv2.imshow("V20 Dynamic Filter", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break
    finally:
        cap.release(); out.release(); cv2.destroyAllWindows()

    # 报表生成时传入设定的目标速度
    generate_fast_response_report(h_t, h_x, h_y, h_v, GLOBAL_TARGET_V)