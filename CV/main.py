import cv2
import numpy as np
import torch
import matplotlib.pyplot as plt
import os

# ==========================================
# 1. 核心追踪器 (V20 变频卡尔曼 + 初速钳位)
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
        
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.001
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 6.0 
        self.kf.errorCovPost = np.eye(4, dtype=np.float32)

    def pixel_to_world(self, u, v):
        src = np.array([[[float(u), float(v)]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(src, self.H)
        return dst[0][0][0], dst[0][0][1]

    def update(self, best_box, timestamp):
        if self.last_t is not None:
            if timestamp < 1.5:
                self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1.0
                self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.01
            else:
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
                v_x = np.clip(v_x, -40.0, 40.0)
                v_y = np.clip(v_y, -40.0, 40.0)
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
# 2. 学术级数据报表
# ==========================================
def generate_academic_report(h_t, h_x, h_y, h_v, target_v, run_name):
    if len(h_t) < 20: return
    
    t, x, y, v = np.array(h_t), np.array(h_x), np.array(h_y), np.array(h_v)
    errors_pct = ((v - target_v) / target_v) * 100

    T_REACTION_END = 1.5   
    T_EVAL_START = 3.0     
    T_EVAL_END = 11.0

    plt.rcParams.update({'font.size': 10, 'axes.linewidth': 1.0})
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f'Kinematic Performance Analysis ($V_{{target}} = {target_v}$ cm/s)', fontsize=14, fontweight='bold', y=0.95)
    plt.subplots_adjust(hspace=0.3, wspace=0.25)

    def draw_eval_zones(ax, t_max):
        ax.axvspan(0, T_REACTION_END, color='#f2dede', alpha=0.5, label='Transient State (<1.5s)')
        ax.axvspan(T_EVAL_START, min(t_max, T_EVAL_END), color='#dff0d8', alpha=0.5, label='Steady State (3-11s)')

    axs[0,0].plot(x, y, color='#4a148c', lw=2.0)
    axs[0,0].axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].axvline(x=180, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].set_title('Spatial Trajectory ($X-Y$ Plane)', fontsize=12)
    axs[0,0].set_xlabel('Displacement $X$ (cm)'); axs[0,0].set_ylabel('Displacement $Y$ (cm)')
    axs[0,0].set_xlim(min(x)-10, max(200, max(x)+10)); axs[0,0].set_ylim(-10, 70)
    axs[0,0].grid(True, linestyle=':', alpha=0.6)

    axs[0,1].plot(t, x, color='#1565c0', label='$X$ Displacement')
    axs[0,1].plot(t, y, color='#e65100', label='$Y$ Displacement')
    draw_eval_zones(axs[0,1], t[-1])
    axs[0,1].set_title('Linear Displacement vs. Time', fontsize=12)
    axs[0,1].set_xlabel('Time $t$ (s)'); axs[0,1].set_ylabel('Position (cm)')
    handles, labels = axs[0,1].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[0,1].legend(by_label.values(), by_label.keys())
    axs[0,1].grid(True, linestyle=':', alpha=0.6)

    axs[1,0].plot(t, v, color='#0d47a1', lw=2.0, label='Estimated $v$')
    axs[1,0].axhline(y=target_v, color='#b71c1c', ls='--', lw=1.5, label=f'Target $v_{{ref}}$ = {target_v}')
    draw_eval_zones(axs[1,0], t[-1])
    axs[1,0].fill_between(t, target_v*0.85, target_v*1.15, color='gray', alpha=0.15, label='$\pm$15% Tolerance')
    axs[1,0].set_title('Velocity Estimation Performance', fontsize=12)
    axs[1,0].set_xlabel('Time $t$ (s)'); axs[1,0].set_ylabel('Velocity $v$ (cm/s)')
    axs[1,0].set_ylim(0, target_v * 1.5) 
    handles, labels = axs[1,0].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[1,0].legend(by_label.values(), by_label.keys(), loc='lower right')
    axs[1,0].grid(True, linestyle=':', alpha=0.6)

    axs[1,1].plot(t, errors_pct, color='#d84315', lw=1.5, label='Relative Error $E$') 
    axs[1,1].axhline(y=0, color='k', lw=1.0)
    axs[1,1].axhline(y=15, color='#b71c1c', ls=':', alpha=0.8, label='Upper Bound (+15%)')
    axs[1,1].axhline(y=-15, color='#b71c1c', ls=':', alpha=0.8, label='Lower Bound (-15%)')
    draw_eval_zones(axs[1,1], t[-1])
    axs[1,1].set_title('Relative Velocity Error Analysis', fontsize=12)
    axs[1,1].set_xlabel('Time $t$ (s)'); axs[1,1].set_ylabel('Error $E$ (%)')
    axs[1,1].set_ylim(-35, 35) 
    handles, labels = axs[1,1].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[1,1].legend(by_label.values(), by_label.keys(), loc='lower right')
    axs[1,1].grid(True, linestyle=':', alpha=0.6)

    save_name = f'Report_V20_Kernel_{run_name}_{target_v}cm_s.png'
    plt.savefig(save_name, dpi=300, bbox_inches='tight')
    print(f"Academic report saved to {save_name}")
    plt.close()

# ==========================================
# 3. 鼠标标定辅助
# ==========================================
pts_clicked = []
def click_event(event, x, y, flags, params):
    global pts_clicked
    frame_disp = params['frame']
    window_name = params['window']
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(pts_clicked) < 4:
            pts_clicked.append([x, y])
            cv2.circle(frame_disp, (x, y), 5, (0, 0, 255), -1)
            if len(pts_clicked) > 1:
                cv2.line(frame_disp, tuple(pts_clicked[-2]), tuple(pts_clicked[-1]), (0, 255, 255), 2)
            if len(pts_clicked) == 4:
                cv2.line(frame_disp, tuple(pts_clicked[3]), tuple(pts_clicked[0]), (0, 255, 255), 2)
            cv2.imshow(window_name, frame_disp)

# ==========================================
# 4. 批处理数据管线
# ==========================================
def process_dataset(video_path, target_v, run_name, cached_data=None):
    global pts_clicked
    print(f"\n[{run_name}] Processing Video: {video_path} (Target: {target_v} cm/s)")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open {video_path}. Skipping.")
        return cached_data

    ret, frame_first = cap.read()
    if not ret: return cached_data

    # --- 修复缓存提取逻辑，同时提取 H 矩阵和 pts_px ---
    H = None
    pts_px = None
    if cached_data is not None:
        use_cache = input(f"[{run_name}] Use previous 180cm calibration box? (y/n): ").strip().lower()
        if use_cache == 'y':
            H, pts_px = cached_data
            
    if H is None or pts_px is None:
        pts_clicked = []
        frame_disp = frame_first.copy()
        window_name = f"Calibration: {run_name}"
        cv2.putText(frame_disp, "Click 180cm Bounds (TL->TR->BR->BL). SPACE to confirm.", 
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow(window_name, frame_disp)
        cv2.setMouseCallback(window_name, click_event, {'frame': frame_disp, 'window': window_name})
        
        print(f"[{run_name}] Waiting for calibration...")
        while True:
            key = cv2.waitKey(1) & 0xFF
            if key == ord(' ') or key == 13: 
                if len(pts_clicked) == 4: break
        cv2.destroyWindow(window_name)
        
        pts_px = np.array(pts_clicked, dtype=np.float32)
        pts_wd = np.float32([[0, 0], [180, 0], [180, 60], [0, 60]]) 
        H = cv2.getPerspectiveTransform(pts_px, pts_wd)

    real_fps = cap.get(cv2.CAP_PROP_FPS)
    if real_fps <= 0 or np.isnan(real_fps): real_fps = 30.0
    
    model = torch.hub.load('ultralytics/yolov5', 'custom', path='best.pt')
    w, h = int(cap.get(3)), int(cap.get(4))
    
    output_vid_name = f'Tracked_{run_name}_{target_v}cm_s.mp4'
    out = cv2.VideoWriter(output_vid_name, cv2.VideoWriter_fourcc(*'mp4v'), real_fps, (w, h))
    
    tracker = TrackerProV20(H)
    h_t, h_x, h_y, h_v = [], [], [], []
    last_px_center = None 

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            # 由于上面确保了 pts_px 被正确缓存或生成，这里不会再报 UnboundLocalError
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
                
                cv2.putText(frame, f"TARGET: {target_v:.1f} cm/s", (40, 40), 0, 1.0, (255, 255, 255), 2)
                cv2.putText(frame, f"VEL: {V_abs:.1f} cm/s", (40, 80), 0, 1.2, (0, 255, 0), 3)
                
                if curr_t < 1.5:
                    cv2.putText(frame, "TRANSIENT STATE (<1.5s)", (40, 130), 0, 1.0, (0, 165, 255), 2)
                elif 3.0 <= curr_t <= 11.0:
                    cv2.putText(frame, "STEADY STATE (3-11s)", (40, 130), 0, 1.0, (0, 255, 0), 2)
                else:
                    cv2.putText(frame, "TRACKING...", (40, 130), 0, 1.0, (255, 255, 255), 2)

            out.write(frame)
            cv2.imshow(f"Processing: {run_name}", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break
    finally:
        cap.release(); out.release(); cv2.destroyAllWindows()

    generate_academic_report(h_t, h_x, h_y, h_v, target_v, run_name)
    print(f"Dataset {run_name} completed.\n")
    
    # 返回元组，把 H 和 pts_px 一起传给下一个视频任务
    return (H, pts_px)

# ==========================================
# 5. 主程序执行序列
# ==========================================
if __name__ == "__main__":
    datasets = [
        {"path": "test_video_21.mp4", "target": 21.0, "name": "Run_21"},
        {"path": "test_video_31.mp4", "target": 31.0, "name": "Run_31"}
    ]
    
    print("========================================")
    print("  Kinematic Evaluation System (V20 Kernel)")
    print("========================================\n")

    # 现在的共享数据是一个元组：(H_matrix, pts_px_array)
    shared_data = None
    
    for ds in datasets:
        if not os.path.exists(ds["path"]):
            print(f"Warning: Video {ds['path']} not found. Skipping.")
            continue
            
        shared_data = process_dataset(ds["path"], ds["target"], ds["name"], cached_data=shared_data)
        
    print("Batch processing finished.") 