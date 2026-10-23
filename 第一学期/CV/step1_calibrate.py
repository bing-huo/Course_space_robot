import cv2
import json
import numpy as np

# 存储鼠标点击的像素坐标
clicked_points = []

def mouse_callback(event, x, y, flags, param):
    global clicked_points
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(clicked_points) < 4:
            clicked_points.append([x, y])
            print(f"已记录点 {len(clicked_points)}: [{x}, {y}]")
            
            # 在图上画圆点
            cv2.circle(frame_disp, (x, y), 5, (0, 0, 255), -1)
            # 连线
            if len(clicked_points) > 1:
                cv2.line(frame_disp, tuple(clicked_points[-2]), tuple(clicked_points[-1]), (0, 255, 255), 2)
            # 第4个点闭合矩形
            if len(clicked_points) == 4:
                cv2.line(frame_disp, tuple(clicked_points[3]), tuple(clicked_points[0]), (0, 255, 255), 2)
            
            cv2.imshow("Calibration - Click 4 points (TL, TR, BR, BL)", frame_disp)

if __name__ == "__main__":
    video_path = "test_video.mp4"
    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    if not ret:
        print("无法读取视频，请检查路径！")
        exit()

    frame_disp = frame.copy()
    cv2.putText(frame_disp, "Click 4 corners: 1.Top-Left -> 2.Top-Right -> 3.Bot-Right -> 4.Bot-Left", 
                (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(frame_disp, "Press 'Q' to save and exit after clicking.", 
                (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    cv2.imshow("Calibration - Click 4 points (TL, TR, BR, BL)", frame_disp)
    cv2.setMouseCallback("Calibration - Click 4 points (TL, TR, BR, BL)", mouse_callback)

    while True:
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    if len(clicked_points) == 4:
        with open('calibration_config.json', 'w') as f:
            json.dump(clicked_points, f)
        print("\n✅ 标定成功！坐标已保存至 calibration_config.json。现在可以运行主测速程序了。")
    else:
        print("\n❌ 标定失败：没有点齐 4 个点。请重新运行。")