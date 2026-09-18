import cv2
import numpy as np
import matplotlib.pyplot as plt
import os
from collections import deque

# ==========================================
# 1. 核心运动学追踪器 (Alpha-Beta 滤波器)
# ==========================================
class KinematicTracker:
    def __init__(self, H_matrix):
        self.H = H_matrix
        self.last_t = None
        self.init_buffer = [] 
        self.vel_inited = False
        
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.initialized = False

    def pixel_to_world(self, u, v):
        src = np.array([[[float(u), float(v)]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(src, self.H)
        return dst[0][0][0], dst[0][0][1]

    def update(self, centroid_px, timestamp, current_phase):
        if centroid_px is None: return None
        
        u, v = centroid_px
        raw_x, raw_y = self.pixel_to_world(u, v)

        if not self.initialized:
            self.x, self.y = raw_x, raw_y
            self.last_t = timestamp
            self.initialized = True
            return self.x, self.y, 0.0, 0.0

        dt = timestamp - self.last_t
        if dt <= 0: dt = 0.033 
        self.last_t = timestamp
        
        if not self.vel_inited:
            self.init_buffer.append((raw_x, raw_y, timestamp))
            if len(self.init_buffer) >= 3:
                p_s, p_e = self.init_buffer[0], self.init_buffer[-1]
                self.vx = (p_e[0] - p_s[0]) / (p_e[2] - p_s[2])
                self.vy = (p_e[1] - p_s[1]) / (p_e[2] - p_s[2])
                self.vel_inited = True
            return self.x, self.y, 0.0, 0.0

        # 动态滤波参数
        if current_phase in ["Phase I: Transient", "Phase II: Convergence"]:
            alpha = 0.85  
            beta  = 0.35  
        else:
            alpha = 0.15  
            beta  = 0.005 

        x_pred = self.x + self.vx * dt
        y_pred = self.y + self.vy * dt
        
        res_x = raw_x - x_pred
        res_y = raw_y - y_pred
        
        self.x = x_pred + alpha * res_x
        self.y = y_pred + alpha * res_y
        self.vx = self.vx + (beta / dt) * res_x
        self.vy = self.vy + (beta / dt) * res_y
        
        self.vx = np.clip(self.vx, -50.0, 50.0)
        self.vy = np.clip(self.vy, -50.0, 50.0)

        return float(self.x), float(self.y), float(self.vx), float(self.vy)

# ==========================================
# 2. 运动状态分类器
# ==========================================
class PhaseClassifier:
    def __init__(self, target_v):
        self.target_v = target_v
        self.v_buffer = deque(maxlen=5) 
        
    def classify(self, t, x, v):
        self.v_buffer.append(v)
        v_smooth = np.mean(self.v_buffer)
        
        if t < 0.5:
            return "Phase I: Transient"
        if x > 165.0:
            return "Phase IV: Terminal"
            
        error_pct = abs(v_smooth - self.target_v) / self.target_v
        if 15.0 <= x <= 165.0 and error_pct <= 0.15:
            return "Phase III: Steady State"
            
        return "Phase II: Convergence"

# ==========================================
# 3. 旗舰学术报表渲染
# ==========================================
def generate_academic_report(h_t, h_x, h_y, h_v, h_phases, target_v, run_name):
    if len(h_t) < 20: return
    
    t, x, y, v = np.array(h_t), np.array(h_x), np.array(h_y), np.array(h_v)
    errors_pct = ((v - target_v) / target_v) * 100

    # 计算稳态区间的平均误差 (用于新增的图表指示线)
    steady_errors = []
    for i, phase in enumerate(h_phases):
        if phase == "Phase III: Steady State":
            steady_errors.append(errors_pct[i])
    mean_steady_error = np.mean(steady_errors) if steady_errors else 0.0

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

    # --- 图 1: 空间轨迹 ---
    axs[0,0].plot(x, y, color='#4a148c', lw=2.0)
    axs[0,0].axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].axvline(x=180, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].set_title('Spatial Trajectory ($X-Y$ Plane)', fontsize=12)
    axs[0,0].set_xlabel('Displacement $X$ (cm)'); axs[0,0].set_ylabel('Displacement $Y$ (cm)')
    axs[0,0].set_xlim(min(x)-10, max(200, max(x)+10)); axs[0,0].set_ylim(-10, 70)
    axs[0,0].grid(True, linestyle=':', alpha=0.6)

    # --- 图 2: 线性位移 ---
    axs[0,1].plot(t, x, color='#1565c0', label='$X$ Displacement')
    axs[0,1].plot(t, y, color='#e65100', label='$Y$ Displacement')
    draw_dynamic_zones(axs[0,1])
    axs[0,1].set_title('Linear Displacement vs. Time', fontsize=12)
    axs[0,1].set_xlabel('Time $t$ (s)'); axs[0,1].set_ylabel('Position (cm)')
    format_legend(axs[0,1], loc='upper left')
    axs[0,1].grid(True, linestyle=':', alpha=0.6)

    # --- 图 3: 速度跟随 ---
    axs[1,0].plot(t, v, color='#0d47a1', lw=2.0, label='Estimated Velocity')
    axs[1,0].axhline(y=target_v, color='#b71c1c', ls='--', lw=1.5, label=f'Target $V_{{ref}}$ = {target_v}')
    draw_dynamic_zones(axs[1,0])
    axs[1,0].fill_between(t, target_v*0.85, target_v*1.15, color='gray', alpha=0.15, label='$\pm$15% Tolerance')
    axs[1,0].set_title('Velocity Estimation Performance', fontsize=12)
    axs[1,0].set_xlabel('Time $t$ (s)'); axs[1,0].set_ylabel('Velocity (cm/s)')
    axs[1,0].set_ylim(0, max(45, target_v * 1.5)) 
    format_legend(axs[1,0], loc='lower right')
    axs[1,0].grid(True, linestyle=':', alpha=0.6)

    # --- 图 4: 相对误差 (新增平均稳态误差标线) ---
    axs[1,1].plot(t, errors_pct, color='#d84315', lw=1.5, label='Relative Error $E$') 
    axs[1,1].axhline(y=0, color='k', lw=1.0)
    axs[1,1].axhline(y=15, color='#b71c1c', ls=':', alpha=0.8, label='Tolerance Bound ($\pm$15%)')
    axs[1,1].axhline(y=-15, color='#b71c1c', ls=':', alpha=0.8)
    
    if steady_errors:
        axs[1,1].axhline(y=mean_steady_error, color='#2ca02c', ls='-.', lw=1.5, 
                         label=f'Mean Steady Error ({mean_steady_error:+.2f}%)')

    draw_dynamic_zones(axs[1,1])
    axs[1,1].set_title('Relative Velocity Error Analysis', fontsize=12)
    axs[1,1].set_xlabel('Time $t$ (s)'); axs[1,1].set_ylabel('Error $E$ (%)')
    axs[1,1].set_ylim(-35, 35) 
    format_legend(axs[1,1], loc='lower right')
    axs[1,1].grid(True, linestyle=':', alpha=0.6)

    # --- 科研底注优化 ---
    footer_text = (
        "Phase Demarcation Criteria:\n"
        "[Phase I] Transient: Initial kinematic acceleration phase ($t < 0.5s$).\n"
        "[Phase II] Convergence: System adaptation prior to achieving steady-state tolerance.\n"
        "[Phase III] Steady State: Engaged when within optimal optical zone ($15 \leq X \leq 165cm$) and error $\leq 15\%$.\n"
        "[Phase IV] Terminal: Egress from calibrated field ($X > 165cm$)."
    )
    fig.text(0.08, 0.02, footer_text, ha='left', va='bottom', fontsize=9.5, color='#333333', 
             bbox=dict(boxstyle='round,pad=0.6', facecolor='#f9f9f9', edgecolor='#cccccc', alpha=0.9))

    save_name = f'Report_Final_{run_name}_{target_v}cm_s.png'
    plt.savefig(save_name, dpi=300, bbox_inches='tight')
    print(f"Final report saved to {save_name}")
    plt.close()

# ==========================================
# 4. 视频渲染与主程序
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
    
    # 采用高精度背景差分
    back_sub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=False)
    roi_mask = np.zeros(frame_first.shape[:2], dtype=np.uint8)
    cv2.fillPoly(roi_mask, [np.int32(pts_px)], 255)
    
    # 视频输出 (标准化命名)
    output_vid_name = f'Tracked_Final_{run_name}_{target_v}cm_s.mp4'
    w, h = int(cap.get(3)), int(cap.get(4))
    out = cv2.VideoWriter(output_vid_name, cv2.VideoWriter_fourcc(*'mp4v'), real_fps, (w, h))
    
    tracker = KinematicTracker(H)
    classifier = PhaseClassifier(target_v)
    H_inv = np.linalg.inv(H)  
    
    h_t, h_x, h_y, h_v, h_phases = [], [], [], [], []
    last_centroid = None 
    traj_pts = deque(maxlen=45) 
    current_phase = "Phase I: Transient" 

    back_sub.apply(frame_first)

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            curr_t = len(h_t) / real_fps 
            
            fg_mask = back_sub.apply(frame)
            fg_mask = cv2.bitwise_and(fg_mask, roi_mask)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            centroid_px = None
            
            if contours:
                largest_contour = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest_contour) > 800: 
                    M = cv2.moments(largest_contour)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        _, _, _, h_box = cv2.boundingRect(largest_contour)
                        cy = int(M["m01"] / M["m00"]) + int(h_box * 0.3)
                        centroid_px = (cx, cy)
                        last_centroid = centroid_px
                        
                        cv2.drawContours(frame, [largest_contour], -1, (0, 255, 0), 2)
                        cv2.circle(frame, centroid_px, 6, (0, 0, 255), -1)

            res = tracker.update(centroid_px, curr_t, current_phase)
            
            overlay = frame.copy()
            cv2.fillPoly(overlay, [np.int32(pts_px)], (255, 100, 0))
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            cv2.polylines(frame, [np.int32(pts_px)], True, (255, 255, 0), 2)

            if res is not None:
                X, Y, Vx, Vy = res
                V_abs = np.sqrt(Vx**2 + Vy**2)
                
                h_t.append(curr_t); h_x.append(X); h_y.append(Y); h_v.append(V_abs)
                current_phase = classifier.classify(curr_t, X, V_abs)
                h_phases.append(current_phase)
                
                if centroid_px is not None:
                    traj_pts.append(centroid_px)
                    if len(traj_pts) > 2:
                        pts_arr = np.array(traj_pts, dtype=np.int32)
                        cv2.polylines(frame, [pts_arr], False, (0, 255, 255), 2)
                    
                    if Vx != 0 or Vy != 0:
                        pred_X, pred_Y = X + Vx * 0.5, Y + Vy * 0.5
                        curr_src = np.array([[[X, Y]]], dtype=np.float32)
                        pred_src = np.array([[[pred_X, pred_Y]]], dtype=np.float32)
                        curr_px = cv2.perspectiveTransform(curr_src, H_inv)[0][0]
                        pred_px = cv2.perspectiveTransform(pred_src, H_inv)[0][0]
                        cv2.arrowedLine(frame, (int(curr_px[0]), int(curr_px[1])), 
                                        (int(pred_px[0]), int(pred_px[1])), (0, 0, 255), 2, tipLength=0.3)
                
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
                # HUD 极简状态显示
                cv2.putText(frame, f"[{current_phase.split(':')[1].strip()}]", (35, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, z_colors.get(current_phase, (255,255,255)), 1)

            out.write(frame)
            cv2.imshow(f"Processing: {run_name}", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break
    finally:
        cap.release(); out.release(); cv2.destroyAllWindows()

    generate_academic_report(h_t, h_x, h_y, h_v, h_phases, target_v, run_name)
    print(f"Dataset {run_name} completed.\n")
    return (H, pts_px)

def _find_baseline(name):
    """定位第一学期基线素材。

    P0.3.g 之后素材归档到 data/v1_baseline/。归档前后都要能跑，
    所以两个位置都找一遍；都找不到就返回归档后的目标路径，交给上层报错。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "data", "v1_baseline", name),
                 os.path.join(here, name)):
        if os.path.exists(cand):
            return os.path.normpath(cand)
    return os.path.normpath(os.path.join(here, "..", "data", "v1_baseline", name))


if __name__ == "__main__":
    datasets = [
        {"path": _find_baseline("test_video_21.mp4"), "target": 21.0, "name": "Run_21"},
        {"path": _find_baseline("test_video_31.mp4"), "target": 31.0, "name": "Run_31"}
    ]
    
    print("========================================")
    print("  Kinematic Evaluation System (Final)")
    print("========================================\n")

    shared_data = None
    for ds in datasets:
        if not os.path.exists(ds["path"]):
            print(f"Warning: Video {ds['path']} not found. Skipping.")
            continue
        shared_data = process_dataset(ds["path"], ds["target"], ds["name"], cached_data=shared_data)
        
    print("All tasks finished successfully.")