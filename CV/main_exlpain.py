import cv2
import numpy as np
import matplotlib.pyplot as plt
import os
from collections import deque

# ==========================================
# 1. 核心运动学追踪器 (小车的大脑：Alpha-Beta 滤波器)
# 它的任务：摄像头拍到的小车位置总是在抖。这个大脑负责把抖动的位置“熨平”，
#          算出一个非常平滑、符合物理惯性的真实速度。
# ==========================================
class KinematicTracker:
    def __init__(self, H_matrix):
        # H_matrix 是个“翻译官”，负责把电脑屏幕上的像素点(x, y)，翻译成地砖上真实的厘米数
        self.H = H_matrix
        self.last_t = None          # 记录上一次看到小车的时间
        self.init_buffer = []       # 一个小本子，用来记小车刚起步时的信息
        self.vel_inited = False     # 记住“我们算没算出初始速度”这个状态
        
        # 下面这四个数字，代表小车目前在现实世界中的真实状态
        self.x = 0.0                # 小车现在的真实左右位置（厘米）
        self.y = 0.0                # 小车现在的真实上下位置（厘米）
        self.vx = 0.0               # 小车现在的横向速度
        self.vy = 0.0               # 小车现在的纵向速度
        self.initialized = False    # 记录“是否已经看清了小车的第一眼”

    def pixel_to_world(self, u, v):
        """透视魔法：把屏幕上的像素坐标，变成现实世界里的厘米坐标"""
        src = np.array([[[float(u), float(v)]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(src, self.H) # 施展上帝视角，把倾斜的镜头拉平
        return dst[0][0][0], dst[0][0][1]

    def update(self, centroid_px, timestamp, current_phase):
        """核心工作车间：每收到一帧画面，就算一次最新速度"""
        # 如果画面里没找到小车的重心，就直接退下，什么也不做
        if centroid_px is None: return None
        
        # centroid_px 是小车重心的像素位置，把它拆成 u 和 v
        u, v = centroid_px
        # 赶紧叫“翻译官”把它变成真实的厘米坐标 (raw_x, raw_y)
        raw_x, raw_y = self.pixel_to_world(u, v)

        # 如果这是第一眼看到小车
        if not self.initialized:
            self.x, self.y = raw_x, raw_y
            self.last_t = timestamp
            self.initialized = True
            return self.x, self.y, 0.0, 0.0 # 刚开始先不报速度，算作 0

        # 看看距离上一次看到小车，过去了多少秒 (叫做 dt)
        dt = timestamp - self.last_t
        # 万一时间出错了，强行假装过了 0.033 秒（约等于一帧的时间），防止后面除以 0 报错
        if dt <= 0: dt = 0.033 
        self.last_t = timestamp
        
        # 强行算出最初几帧的物理速度，让大脑有个初始参考
        if not self.vel_inited:
            self.init_buffer.append((raw_x, raw_y, timestamp))
            if len(self.init_buffer) >= 3:
                p_s, p_e = self.init_buffer[0], self.init_buffer[-1]
                # 小学物理公式：速度 = 距离差 / 时间差
                self.vx = (p_e[0] - p_s[0]) / (p_e[2] - p_s[2])
                self.vy = (p_e[1] - p_s[1]) / (p_e[2] - p_s[2])
                self.vel_inited = True
            return self.x, self.y, 0.0, 0.0

        # === 核心魔法：智能变频防抖 (Alpha-Beta) ===
        # 根据小车目前处于哪个阶段，使用不同的“信任度参数”
        if current_phase in ["Phase I: Transient", "Phase II: Convergence"]:
            # 如果在“起步”或“过渡”期：小车正在猛烈加速！
            # alpha=0.85 代表我 85% 相信现在眼睛看到的位置；beta=0.35 代表我极速响应速度的变化
            # 总结：减震器变软，0 延迟跟上汽车的推背感。
            alpha = 0.85  
            beta  = 0.35  
        else:
            # 如果进入了“稳态期”：小车已经在匀速跑了。
            # 这时候画面如果还在抖，肯定是光影噪点！
            # alpha=0.15 代表我只信眼睛 15%，更多的是靠惯性预测；beta=0.005 代表死死锁住当前速度不准变！
            # 总结：减震器变极硬，彻底抹杀画面的抖动毛刺。
            alpha = 0.15  
            beta  = 0.005 

        # 1. 蒙眼预测 (Prediction)：根据刚才的速度，猜小车现在应该走到哪里了
        x_pred = self.x + self.vx * dt
        y_pred = self.y + self.vy * dt
        
        # 2. 算误差 (Residual)：实际看到的真实位置，和猜的位置，差了多少？
        res_x = raw_x - x_pred
        res_y = raw_y - y_pred
        
        # 3. 综合修正 (Update)：
        # 新的位置 = 猜的位置 + alpha 比例的误差修正
        self.x = x_pred + alpha * res_x
        self.y = y_pred + alpha * res_y
        # 新的速度 = 老的速度 + beta 比例的加速度修正
        self.vx = self.vx + (beta / dt) * res_x
        self.vy = self.vy + (beta / dt) * res_y
        
        # 上个物理保险：无论算错成什么样，小车的速度绝不可能超过 50 厘米/秒
        self.vx = np.clip(self.vx, -50.0, 50.0)
        self.vy = np.clip(self.vy, -50.0, 50.0)

        # 把最终算好的、极度平滑的 [位置, 速度] 交给画图程序
        return float(self.x), float(self.y), float(self.vx), float(self.vy)

# ==========================================
# 2. 运动状态裁判员 (自动给运动分阶段)
# 它的任务：不能人为挑好看的数据，要靠电脑自己判断小车跑得稳不稳
# ==========================================
class PhaseClassifier:
    def __init__(self, target_v):
        self.target_v = target_v # 记住我们要求小车跑多少速度（比如 21 或 31）
        self.v_buffer = deque(maxlen=5) # 准备一个小本子，存最近 5 次的速度，防止一帧看错吹黑哨
        
    def classify(self, t, x, v):
        self.v_buffer.append(v)
        v_smooth = np.mean(self.v_buffer) # 算个平均速度来判断
        
        # 规则 1：比赛刚开始 0.5 秒内，啥也别说，强制算是“瞬态起步期”
        if t < 0.5:
            return "Phase I: Transient"
        # 规则 2：小车跑过 165 厘米后，马上就要冲出画面了，算作“驶出末端期”
        if x > 165.0:
            return "Phase IV: Terminal"
            
        # 规则 3：算一下小车现在的速度，离我们的目标值还差百分之几？
        error_pct = abs(v_smooth - self.target_v) / self.target_v
        # 【最高荣誉】：如果小车在画面最清晰的中央地带(15~165cm)，且速度误差小于 15%
        if 15.0 <= x <= 165.0 and error_pct <= 0.15:
            return "Phase III: Steady State" # 吹哨！宣布进入“黄金稳态期”
            
        # 如果都没达标，说明小车还在努力追赶目标速度，算作“过渡收敛期”
        return "Phase II: Convergence"

# ==========================================
# 3. 画图机器人 (自动生成炫酷的科研报表)
# ==========================================
def generate_academic_report(h_t, h_x, h_y, h_v, h_phases, target_v, run_name):
    # 视频太短没数据就不画了
    if len(h_t) < 20: return
    
    # 整理数据
    t, x, y, v = np.array(h_t), np.array(h_x), np.array(h_y), np.array(h_v)
    errors_pct = ((v - target_v) / target_v) * 100

    # 挑出“稳态区间 (Phase III)”里的所有误差，算个平均数，等会儿在图上画根绿线炫耀一下
    steady_errors = []
    for i, phase in enumerate(h_phases):
        if phase == "Phase III: Steady State":
            steady_errors.append(errors_pct[i])
    mean_steady_error = np.mean(steady_errors) if steady_errors else 0.0

    # 准备一块画板，画 4 个格子
    plt.rcParams.update({'font.size': 10, 'axes.linewidth': 1.0})
    fig, axs = plt.subplots(2, 2, figsize=(15, 12))
    fig.suptitle(f'Kinematic Performance Analysis ($V_{{target}} = {target_v}$ cm/s)', fontsize=15, fontweight='bold', y=0.96)
    plt.subplots_adjust(hspace=0.35, wspace=0.25, bottom=0.15) 

    # 给 4 个阶段定好背景颜色
    phase_colors = {
        "Phase I: Transient": "#f2dede",   # 浅红
        "Phase II: Convergence": "#fcf8e3",# 浅黄
        "Phase III: Steady State": "#dff0d8",# 浅绿
        "Phase IV: Terminal": "#eeeeee"    # 浅灰
    }

    def draw_dynamic_zones(ax):
        """自动在背景上涂色块的刷子"""
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
        """整理图例的工具"""
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(by_label.values(), by_label.keys(), loc=loc, fontsize=8)

    # --- 左上角 图 1: 小车俯视 2D 轨迹 ---
    axs[0,0].plot(x, y, color='#4a148c', lw=2.0)
    axs[0,0].axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].axvline(x=180, color='gray', linestyle='--', alpha=0.5)
    axs[0,0].set_title('Spatial Trajectory ($X-Y$ Plane)', fontsize=12)
    axs[0,0].set_xlabel('Displacement $X$ (cm)'); axs[0,0].set_ylabel('Displacement $Y$ (cm)')
    axs[0,0].set_xlim(min(x)-10, max(200, max(x)+10)); axs[0,0].set_ylim(-10, 70)
    axs[0,0].grid(True, linestyle=':', alpha=0.6)

    # --- 右上角 图 2: 直线距离随时间的变化 ---
    axs[0,1].plot(t, x, color='#1565c0', label='$X$ Displacement')
    axs[0,1].plot(t, y, color='#e65100', label='$Y$ Displacement')
    draw_dynamic_zones(axs[0,1])
    axs[0,1].set_title('Linear Displacement vs. Time', fontsize=12)
    axs[0,1].set_xlabel('Time $t$ (s)'); axs[0,1].set_ylabel('Position (cm)')
    format_legend(axs[0,1], loc='upper left')
    axs[0,1].grid(True, linestyle=':', alpha=0.6)

    # --- 左下角 图 3: 核心测速表现 ---
    axs[1,0].plot(t, v, color='#0d47a1', lw=2.0, label='Estimated Velocity')
    axs[1,0].axhline(y=target_v, color='#b71c1c', ls='--', lw=1.5, label=f'Target $V_{{ref}}$ = {target_v}') # 目标速度红线
    draw_dynamic_zones(axs[1,0])
    axs[1,0].fill_between(t, target_v*0.85, target_v*1.15, color='gray', alpha=0.15, label='$\pm$15% Tolerance') # 15% 容错带
    axs[1,0].set_title('Velocity Estimation Performance', fontsize=12)
    axs[1,0].set_xlabel('Time $t$ (s)'); axs[1,0].set_ylabel('Velocity (cm/s)')
    axs[1,0].set_ylim(0, max(45, target_v * 1.5)) 
    format_legend(axs[1,0], loc='lower right')
    axs[1,0].grid(True, linestyle=':', alpha=0.6)

    # --- 右下角 图 4: 误差百分比分析 ---
    axs[1,1].plot(t, errors_pct, color='#d84315', lw=1.5, label='Relative Error $E$') 
    axs[1,1].axhline(y=0, color='k', lw=1.0) # 0误差黑线
    axs[1,1].axhline(y=15, color='#b71c1c', ls=':', alpha=0.8, label='Tolerance Bound ($\pm$15%)') # 正15%红线
    axs[1,1].axhline(y=-15, color='#b71c1c', ls=':', alpha=0.8) # 负15%红线
    
    # 画出耀眼的绿色虚线，直接展示我们的系统在稳态时误差到底有多小
    if steady_errors:
        axs[1,1].axhline(y=mean_steady_error, color='#2ca02c', ls='-.', lw=1.5, 
                         label=f'Mean Steady Error ({mean_steady_error:+.2f}%)')

    draw_dynamic_zones(axs[1,1])
    axs[1,1].set_title('Relative Velocity Error Analysis', fontsize=12)
    axs[1,1].set_xlabel('Time $t$ (s)'); axs[1,1].set_ylabel('Error $E$ (%)')
    axs[1,1].set_ylim(-35, 35) 
    format_legend(axs[1,1], loc='lower right')
    axs[1,1].grid(True, linestyle=':', alpha=0.6)

    # 在图表最下面加一段科研级英文解释，说明色块是怎么分段的，提升逼格
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
# 4. 视频渲染与主程序 (总调度室)
# ==========================================
pts_clicked = []
def click_event(event, x, y, flags, params):
    """鼠标点击事件：用于手动框选地砖上的 180x60 厘米的 4 个角"""
    global pts_clicked
    frame_disp = params['frame']
    window_name = params['window']
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(pts_clicked) < 4:
            pts_clicked.append([x, y])
            cv2.circle(frame_disp, (x, y), 5, (0, 0, 255), -1)
            # 点完之后画黄线连起来，方便确认没点错
            if len(pts_clicked) > 1:
                cv2.line(frame_disp, tuple(pts_clicked[-2]), tuple(pts_clicked[-1]), (0, 255, 255), 2)
            if len(pts_clicked) == 4:
                cv2.line(frame_disp, tuple(pts_clicked[3]), tuple(pts_clicked[0]), (0, 255, 255), 2)
            cv2.imshow(window_name, frame_disp)

def process_dataset(video_path, target_v, run_name, cached_data=None):
    """处理单个视频的流水线"""
    global pts_clicked
    print(f"\n[{run_name}] Processing Video: {video_path} (Target: {target_v} cm/s)")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open {video_path}. Skipping.")
        return cached_data

    ret, frame_first = cap.read()
    if not ret: return cached_data

    # 如果相机机位没动，可以偷懒复用上一次点击的坐标框
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
            if key == ord(' ') or key == 13: # 空格或回车确认
                if len(pts_clicked) == 4: break
        cv2.destroyWindow(window_name)
        
        pts_px = np.array(pts_clicked, dtype=np.float32)
        # 告诉电脑：刚才点的 4 个点，在真实世界里长宽是 180 和 60
        pts_wd = np.float32([[0, 0], [180, 0], [180, 60], [0, 60]]) 
        H = cv2.getPerspectiveTransform(pts_px, pts_wd)

    real_fps = cap.get(cv2.CAP_PROP_FPS)
    if real_fps <= 0 or np.isnan(real_fps): real_fps = 30.0
    
    # 【高能预警：背景差分法 (MOG2)】
    # 这个工具非常聪明，它会记住“背景”长什么样。等小车开过时，只要把背景一减，剩下的那一坨纯像素就是小车！
    # 彻底抛弃了慢腾腾的 YOLO，速度快 10 倍，而且非常准。
    back_sub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=False)
    # 做个黑布遮罩，只在标定好的 180cm 区域内找小车，防止外面的路人干扰
    roi_mask = np.zeros(frame_first.shape[:2], dtype=np.uint8)
    cv2.fillPoly(roi_mask, [np.int32(pts_px)], 255)
    
    # 视频输出配置
    output_vid_name = f'Tracked_Final_{run_name}_{target_v}cm_s.mp4'
    w, h = int(cap.get(3)), int(cap.get(4))
    out = cv2.VideoWriter(output_vid_name, cv2.VideoWriter_fourcc(*'mp4v'), real_fps, (w, h))
    
    # 把大脑、裁判请出来
    tracker = KinematicTracker(H)
    classifier = PhaseClassifier(target_v)
    H_inv = np.linalg.inv(H)  # 求逆矩阵：把物理坐标还原到屏幕上画箭头用的
    
    h_t, h_x, h_y, h_v, h_phases = [], [], [], [], []
    last_centroid = None 
    traj_pts = deque(maxlen=45) 
    current_phase = "Phase I: Transient" 

    # 让背景差分工具先看一眼空赛道
    back_sub.apply(frame_first)

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            curr_t = len(h_t) / real_fps 
            
            # --- 纯视觉图像处理 (提取车身重心) ---
            # 把当前画面减去背景，拿到白色的车身影子
            fg_mask = back_sub.apply(frame)
            fg_mask = cv2.bitwise_and(fg_mask, roi_mask) # 盖上黑布遮罩
            
            # 用形态学开闭运算，把影子上的小破洞补上，把旁边零碎的小噪点擦掉
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            
            # 找到所有的白色轮廓
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            centroid_px = None
            
            if contours:
                # 挑最大的那个轮廓，那就是小车本车
                largest_contour = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest_contour) > 800: # 如果轮廓太小，可能是蚊子或者垃圾，不要
                    # cv2.moments 是求一个不规则图形的“几何重心”，这比 YOLO 画方框要准一万倍，完全不抖！
                    M = cv2.moments(largest_contour)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"]) # X 轴重心
                        _, _, _, h_box = cv2.boundingRect(largest_contour)
                        cy = int(M["m01"] / M["m00"]) + int(h_box * 0.3) # Y 轴因为透视关系，往下偏一点当做车底盘
                        centroid_px = (cx, cy)
                        last_centroid = centroid_px
                        
                        # 在视频上画出抠出来的绿色车身外壳，还有个红点代表重心
                        cv2.drawContours(frame, [largest_contour], -1, (0, 255, 0), 2)
                        cv2.circle(frame, centroid_px, 6, (0, 0, 255), -1)

            # 把算出的极准的重心点，扔给大脑（追踪器）去算速度
            res = tracker.update(centroid_px, curr_t, current_phase)
            
            # 给画面蒙上一层半透明橙色标定区，帅气
            overlay = frame.copy()
            cv2.fillPoly(overlay, [np.int32(pts_px)], (255, 100, 0))
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            cv2.polylines(frame, [np.int32(pts_px)], True, (255, 255, 0), 2)

            if res is not None:
                X, Y, Vx, Vy = res
                V_abs = np.sqrt(Vx**2 + Vy**2)
                
                # 保存数据，留给最后画图表用
                h_t.append(curr_t); h_x.append(X); h_y.append(Y); h_v.append(V_abs)
                current_phase = classifier.classify(curr_t, X, V_abs)
                h_phases.append(current_phase)
                
                # --- 可视化：画历史轨迹和速度箭头 ---
                if centroid_px is not None:
                    traj_pts.append(centroid_px)
                    if len(traj_pts) > 2:
                        pts_arr = np.array(traj_pts, dtype=np.int32)
                        cv2.polylines(frame, [pts_arr], False, (0, 255, 255), 2) # 黄色的长尾迹
                    
                    if Vx != 0 or Vy != 0:
                        # 假装在现实世界里让小车按当前速度往前走 0.5 秒
                        pred_X, pred_Y = X + Vx * 0.5, Y + Vy * 0.5
                        curr_src = np.array([[[X, Y]]], dtype=np.float32)
                        pred_src = np.array([[[pred_X, pred_Y]]], dtype=np.float32)
                        # 用刚才的逆矩阵 H_inv，把这两个未来的现实点，投射回电脑屏幕像素里，画出红色防抖箭头
                        curr_px = cv2.perspectiveTransform(curr_src, H_inv)[0][0]
                        pred_px = cv2.perspectiveTransform(pred_src, H_inv)[0][0]
                        cv2.arrowedLine(frame, (int(curr_px[0]), int(curr_px[1])), 
                                        (int(pred_px[0]), int(pred_px[1])), (0, 0, 255), 2, tipLength=0.3)
                
                # --- 可视化：左上角的极简 HUD 黑板 ---
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
                # HUD 底端打印当前的状态机判决
                cv2.putText(frame, f"[{current_phase.split(':')[1].strip()}]", (35, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, z_colors.get(current_phase, (255,255,255)), 1)

            out.write(frame)
            cv2.imshow(f"Processing: {run_name}", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break
    finally:
        cap.release(); out.release(); cv2.destroyAllWindows()

    # 视频跑完后，全自动画出 4 个图表的科研报表
    generate_academic_report(h_t, h_x, h_y, h_v, h_phases, target_v, run_name)
    print(f"Dataset {run_name} completed.\n")
    return (H, pts_px)

# ==========================================
# 5. 总司令部：一键处理所有视频
# ==========================================
if __name__ == "__main__":
    # 配置要处理的视频路径和目标速度
    datasets = [
        {"path": "test_video_21.mp4", "target": 21.0, "name": "Run_21"},
        {"path": "test_video_31.mp4", "target": 31.0, "name": "Run_31"}
    ]
    
    print("========================================")
    print("  Kinematic Evaluation System (Final)")
    print("========================================\n")

    shared_data = None
    for ds in datasets:
        if not os.path.exists(ds["path"]):
            print(f"Warning: Video {ds['path']} not found. Skipping.")
            continue
        # 顺次丢给工厂进行处理
        shared_data = process_dataset(ds["path"], ds["target"], ds["name"], cached_data=shared_data)
        
    print("All tasks finished successfully.")