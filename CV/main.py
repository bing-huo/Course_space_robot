import cv2
import numpy as np
import torch
import matplotlib.pyplot as plt
import os
from collections import deque

# ==========================================
# 1. 核心状态估计器 (纯净 V20 变频卡尔曼内核)
# ==========================================
class AcademicTrackerV20_Enhanced:
    def __init__(self, H_matrix, max_lost=30):
        self.H = H_matrix
        self.last_t = None
        self.init_buffer = [] 
        self.vel_inited = False
        self.lost_count = 0
        self.max_lost = max_lost
        
        # EMA 框平滑，抑制边缘呼吸效应
        self.ema_box = None
        self.ema_alpha = 0.3  
        
        # 纯净卡尔曼滤波器，无 Polyfit 回归
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        self.kf.transitionMatrix = np.eye(4, dtype=np.float32)
        
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.001
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 6.0 

    def pixel_to_world(self, u, v):
        src = np.array([[[float(u), float(v)]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(src, self.H)
        return dst[0][0][0], dst[0][0][1]

    def update(self, best_box, timestamp):
        # 变频卡尔曼：前1.5s极速收敛，后半段死锁平滑
        if self.last_t is not None:
            if timestamp < 1.5:
                self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1.0
                self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.01
            else:
                self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 6.0
                self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.001

        if best_box is not None:
            if self.ema_box is None: 
                self.ema_box = best_box
            else: 
                self.ema_box = self.ema_alpha * best_box + (1 - self.ema_alpha) * self.ema_box
            u, v_bot = (self.ema_box[0] + self.ema_box[2]) / 2, self.ema_box[3]
            curr_x, curr_y = self.pixel_to_world(u, v_bot)
        else:
            curr_x, curr_y = None, None

        if self.last_t is None:
            if curr_x is None: return None
            self.last_t = timestamp
            return curr_x, curr_y, 0.0, 0.0

        dt = timestamp - self.last_t
        self.last_t = timestamp
        
        # 初速钳位
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
            return curr_x, curr_y, 0.0, 0.0

        self.kf.transitionMatrix[0, 2] = dt
        self.kf.transitionMatrix[1, 3] = dt
        
        if best_box is not None:
            self.lost_count = 0
            meas = np.array([[np.float32(curr_x)], [np.float32(curr_y)]])
            self.kf.predict()
            state = self.kf.correct(meas)
        else:
            self.lost_count += 1
            state = self.kf.predict()

        if self.lost_count > self.max_lost:
            self.ema_box = None
            return None

        # 完全输出卡尔曼原生状态 (V20 特性)
        x, y, vx, vy = state.flatten()
        return float(x), float(y), float(vx), float(vy)

# ==========================================
# 2. 动态状态分类器 (主动识别)
# ==========================================
class PhaseClassifier:
    def __init__(self):
        self.v_buffer = deque(maxlen=15)
        
    def classify(self, t, x, v):
        self.v_buffer.append(v)
        
        if t < 1.5:
            return "Phase I: Transient"
        if x > 160.0:
            return "Phase IV: Terminal"
            
        if len(self.v_buffer) == 15:
            v_std = np.std(self.v_buffer)
            # 在 20~160cm 腹地，且速度收敛时，判定为稳态
            if 20.0 <= x <= 160.0 and v_std < 3.0:
                return "Phase III: Steady State"
                
        return "Phase II: Convergence"

# ==========================================
# 3. 智能渲染学术报表
# ==========================================
def generate_auto_academic_report(h_t, h_x, h_y, h_v, h_phases, target_v, run_name):
    if len(h_t) < 20: return
    
    t, x, y, v = np.array(h_t), np.array(h_x), np.array(h_y), np.array(h_v)
    errors_pct = ((v - target_v) / target_v) * 100

    plt.rcParams.update({'font.size': 10, 'axes.linewidth': 1.0})
    fig, axs = plt.subplots(2, 2, figsize=(15, 12))
    fig.suptitle(f'Kinematic Performance Analysis ($V_{{target}} = {target_v}$ cm/s)', fontsize=15, fontweight='bold', y=0.96)
    plt.subplots_adjust(hspace=0.35, wspace=0.25, bottom=0.15) 

    phase_colors = {
        "Phase I: Transient": "#f2dede",   
        "Phase II: Convergence": "#fcf8e3",
        "Phase III: Steady State": "#dff0d8",
        "Phase IV: Terminal": "#eeeeee"    
    }

    def draw_dynamic_zones(ax):
        start_idx = 0
        current_phase = h_phases[0]
        for i in range(1, len(h_t)):
            if h_phases[i] != current_phase or i == len(h_t) - 1:
                end_idx = i if h_phases[i] != current_phase else i + 1
                t_start = t[start_idx]
                t_end = t[end_idx - 1]
                ax.axvspan(t_start, t_end, color=phase_colors[current_phase], alpha=0.6, label=current_phase)
                current_phase = h_phases[i]
                start_idx = i

    def format_legend(ax, loc='best'):
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(by_label.values(), by_label.keys(), loc=loc, fontsize=8)

    axs[0,0].plot(x, y, color='#4a148c', lw=2.0)
    axs[0,0].axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].axvline(x=180, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].set_title('Spatial Trajectory ($X-Y$ Plane)', fontsize=12)
    axs[0,0].set_xlabel('Displacement $X$ (cm)'); axs[0,0].set_ylabel('Displacement $Y$ (cm)')
    axs[0,0].set_xlim(min(x)-10, max(200, max(x)+10)); axs[0,0].set_ylim(-10, 70)
    axs[0,0].grid(True, linestyle=':', alpha=0.6)

    axs[0,1].plot(t, x, color='#1565c0', label='$X$ Displacement')
    axs[0,1].plot(t, y, color='#e65100', label='$Y$ Displacement')
    draw_dynamic_zones(axs[0,1])
    axs[0,1].set_title('Linear Displacement vs. Time', fontsize=12)
    axs[0,1].set_xlabel('Time $t$ (s)'); axs[0,1].set_ylabel('Position (cm)')
    format_legend(axs[0,1], loc='upper left')
    axs[0,1].grid(True, linestyle=':', alpha=0.6)

    axs[1,0].plot(t, v, color='#0d47a1', lw=2.0, label='Estimated $v$')
    axs[1,0].axhline(y=target_v, color='#b71c1c', ls='--', lw=1.5, label=f'Target $v_{{ref}}$ = {target_v}')
    draw_dynamic_zones(axs[1,0])
    axs[1,0].fill_between(t, target_v*0.85, target_v*1.15, color='gray', alpha=0.15, label='$\pm$15% Tolerance')
    axs[1,0].set_title('Velocity Estimation Performance', fontsize=12)
    axs[1,0].set_xlabel('Time $t$ (s)'); axs[1,0].set_ylabel('Velocity $v$ (cm/s)')
    axs[1,0].set_ylim(0, max(45, target_v * 1.5)) 
    format_legend(axs[1,0], loc='lower right')
    axs[1,0].grid(True, linestyle=':', alpha=0.6)

    axs[1,1].plot(t, errors_pct, color='#d84315', lw=1.5, label='Relative Error $E$') 
    axs[1,1].axhline(y=0, color='k', lw=1.0)
    axs[1,1].axhline(y=15, color='#b71c1c', ls=':', alpha=0.8, label='Upper Bound (+15%)')
    axs[1,1].axhline(y=-15, color='#b71c1c', ls=':', alpha=0.8, label='Lower Bound (-15%)')
    draw_dynamic_zones(axs[1,1])
    axs[1,1].set_title('Relative Velocity Error Analysis', fontsize=12)
    axs[1,1].set_xlabel('Time $t$ (s)'); axs[1,1].set_ylabel('Error $E$ (%)')
    axs[1,1].set_ylim(-35, 35) 
    format_legend(axs[1,1], loc='lower right')
    axs[1,1].grid(True, linestyle=':', alpha=0.6)

    footer_text = (
        "Phase Classification Logic (Auto-Driven):\n"
        "[Phase I] Transient: t < 1.5s. Initial algorithmic acceleration.\n"
        "[Phase II] Convergence: Adapting to the dynamic state. Outside optical sweet spot or velocity variance is high.\n"
        "[Phase III] Steady State: 20cm \u2264 X \u2264 160cm AND rolling standard deviation of velocity \u03c3 < 3.0.\n"
        "[Phase IV] Terminal: X > 160cm. Exiting the optimal optical field."
    )
    fig.text(0.08, 0.02, footer_text, ha='left', va='bottom', fontsize=9.5, color='#333333', 
             bbox=dict(boxstyle='round,pad=0.6', facecolor='#f9f9f9', edgecolor='#cccccc', alpha=0.9))

    save_name = f'Report_V20_Enhanced_{run_name}_{target_v}cm_s.png'
    plt.savefig(save_name, dpi=300, bbox_inches='tight')
    print(f"Academic report saved to {save_name}")
    plt.close()

# ==========================================
# 4. 视频批处理与渲染管线
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

def process_dataset(video_path, target_v, run_name, cached_data=None):
    global pts_clicked
    print(f"\n[{run_name}] Processing Video: {video_path} (Target: {target_v} cm/s)")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open {video_path}. Skipping.")
        return cached_data

    ret, frame_first = cap.read()
    if not ret: return cached_data

    H, pts_px = None, None
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
    
    output_vid_name = f'Tracked_V20_Enhanced_{run_name}_{target_v}cm_s.mp4'
    out = cv2.VideoWriter(output_vid_name, cv2.VideoWriter_fourcc(*'mp4v'), real_fps, (w, h))
    
    tracker = AcademicTrackerV20_Enhanced(H)
    classifier = PhaseClassifier()
    H_inv = np.linalg.inv(H)  # 逆单应性矩阵用于矢量投影
    
    h_t, h_x, h_y, h_v, h_phases = [], [], [], [], []
    last_px_center = None 
    traj_pts = deque(maxlen=45) 

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
                X, Y, Vx, Vy = res
                V_abs = np.sqrt(Vx**2 + Vy**2)
                
                h_t.append(curr_t); h_x.append(X); h_y.append(Y); h_v.append(V_abs)
                current_phase = classifier.classify(curr_t, X, V_abs)
                h_phases.append(current_phase)
                
                if best_box is not None:
                    last_px_center = ((best_box[0]+best_box[2])/2, (best_box[1]+best_box[3])/2)
                    x1, y1, x2, y2 = map(int, best_box[:4])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 1)
                    
                    # 绘制历史轨迹 (Trajectory)
                    traj_pts.append(last_px_center)
                    if len(traj_pts) > 2:
                        pts_arr = np.array(traj_pts, dtype=np.int32)
                        cv2.polylines(frame, [pts_arr], False, (0, 255, 255), 2)
                    
                    # 绘制逆透视速度矢量 (Speed Vector)
                    if Vx != 0 or Vy != 0:
                        pred_X, pred_Y = X + Vx * 0.5, Y + Vy * 0.5
                        curr_src = np.array([[[X, Y]]], dtype=np.float32)
                        pred_src = np.array([[[pred_X, pred_Y]]], dtype=np.float32)
                        curr_px = cv2.perspectiveTransform(curr_src, H_inv)[0][0]
                        pred_px = cv2.perspectiveTransform(pred_src, H_inv)[0][0]
                        cv2.arrowedLine(frame, (int(curr_px[0]), int(curr_px[1])), 
                                        (int(pred_px[0]), int(pred_px[1])), (0, 0, 255), 2, tipLength=0.3)
                
                # HUD 面板渲染
                panel_color = (40, 40, 40)
                cv2.rectangle(frame, (20, 20), (380, 160), panel_color, -1)
                cv2.rectangle(frame, (20, 20), (380, 160), (200, 200, 200), 1)
                
                err_val = ((V_abs - target_v) / target_v) * 100
                cv2.putText(frame, f"TARGET : {target_v:.1f} cm/s", (35, 55), cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), 1)
                cv2.putText(frame, f"MEASURE: {V_abs:.1f} cm/s", (35, 90), cv2.FONT_HERSHEY_DUPLEX, 0.7, (0, 255, 0), 1)
                cv2.putText(frame, f"ERROR  : {err_val:+.1f} %", (35, 125), cv2.FONT_HERSHEY_DUPLEX, 0.7, 
                            (0, 0, 255) if abs(err_val)>15 else (255, 255, 255), 1)
                
                z_colors = {
                    "Phase I: Transient": (0, 100, 255),
                    "Phase II: Convergence": (0, 255, 255),
                    "Phase III: Steady State": (0, 255, 0),
                    "Phase IV: Terminal": (150, 150, 150)
                }
                cv2.putText(frame, f"[{current_phase.split(':')[1].strip()}]", (35, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, z_colors.get(current_phase, (255,255,255)), 1)

            out.write(frame)
            cv2.imshow(f"Auto-Phase Tracking: {run_name}", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break
    finally:
        cap.release(); out.release(); cv2.destroyAllWindows()

    generate_auto_academic_report(h_t, h_x, h_y, h_v, h_phases, target_v, run_name)
    print(f"Dataset {run_name} completed.\n")
    return (H, pts_px)

# ==========================================
# 5. 批处理入口
# ==========================================
if __name__ == "__main__":
    datasets = [
        {"path": "test_video_21.mp4", "target": 21.0, "name": "Run_21"},
        {"path": "test_video_31.mp4", "target": 31.0, "name": "Run_31"}
    ]
    
    print("========================================")
    print("  Kinematic System V20-Enhanced")
    print("  (Pure Kalman + Tracking + Vectors + Auto-Phase)")
    print("========================================\n")

    shared_data = None
    for ds in datasets:
        if not os.path.exists(ds["path"]):
            print(f"Warning: Video {ds['path']} not found. Skipping.")
            continue
            
        shared_data = process_dataset(ds["path"], ds["target"], ds["name"], cached_data=shared_data)
        
    print("Batch processing finished.")