#!/usr/bin/env python3
"""
Zoom effect using ffmpeg zoompan with frame-based expressions (on/30 = seconds at 30fps).
Splits video into segments and applies zoom to event windows, then concatenates.
"""
import sys
import json
import subprocess
import os
import tempfile

ZOOM_FACTOR = 1.35
RAMP_IN = 0.35
HOLD = 0.6
RAMP_OUT = 0.35
WINDOW = RAMP_IN + HOLD + RAMP_OUT  # 1.3s total

def get_video_info(video_path):
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", video_path],
        capture_output=True, text=True
    )
    info = json.loads(probe.stdout)
    vstream = next(s for s in info["streams"] if s["codec_type"] == "video")
    width, height = vstream["width"], vstream["height"]
    fps_num, fps_den = map(int, vstream["r_frame_rate"].split("/"))
    fps = fps_num / fps_den
    return width, height, fps

def get_duration(video_path):
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True, text=True
    )
    info = json.loads(probe.stdout)
    return float(info["format"]["duration"])

def main(video_path, events_path, sync_offset=0.3):
    with open(events_path) as f:
        events = json.load(f)
    # Компенсируем задержку визуальной анимации курсора (transition: .2s)
    # + небольшой запас на латентность самого клика/ripple
    for ev in events:
        ev["time"] += sync_offset

    width, height, fps = get_video_info(video_path)
    duration = get_duration(video_path)
    events = sorted(events, key=lambda e: e["time"])
    
    print(f"→ Video: {width}x{height} @ {fps}fps, {duration:.1f}s, {len(events)} events")

    with tempfile.TemporaryDirectory() as tmpdir:
        segment_files = []
        last_end = 0
        
        for i, ev in enumerate(events):
            t = ev["time"]
            cx, cy = ev["x"], ev["y"]
            
            win_start = max(0, t - RAMP_IN)
            win_end = min(duration, t + HOLD + RAMP_OUT)
            
            # Normal segment before window
            if win_start > last_end:
                seg_file = os.path.join(tmpdir, f"seg_{len(segment_files):03d}_norm.mp4")
                subprocess.run([
                    "ffmpeg", "-y", "-i", video_path,
                    "-ss", str(last_end), "-to", str(win_start),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-pix_fmt", "yuv420p",
                    seg_file
                ], check=True, capture_output=True)
                segment_files.append(seg_file)
            
            # Zoom segment
            if win_end > win_start:
                seg_file = os.path.join(tmpdir, f"seg_{len(segment_files):03d}_zoom.mp4")
                seg_duration = win_end - win_start
                
                # Frame-based expressions (on is frame number starting at 0)
                # Convert time to frame counts
                ramp_in_frames = int(RAMP_IN * fps)
                hold_frames = int(HOLD * fps)
                ramp_out_frames = int(RAMP_OUT * fps)
                window_frames = ramp_in_frames + hold_frames + ramp_out_frames
                
                nx = cx / width
                ny = cy / height
                
                # Zoom expression using frame number (on)
                z_expr = (
                    f"if(lt(on,{ramp_in_frames}),"
                    f"  1+({ZOOM_FACTOR}-1)*on/{ramp_in_frames},"
                    f" if(lt(on,{ramp_in_frames + hold_frames}),"
                    f"  {ZOOM_FACTOR},"
                    f" if(lt(on,{window_frames}),"
                    f"  {ZOOM_FACTOR}-({ZOOM_FACTOR}-1)*(on-{ramp_in_frames + hold_frames})/{ramp_out_frames},"
                    f"  1)))"
                )
                x_expr = f"iw*{nx}-iw/zoom/2"
                y_expr = f"ih*{ny}-ih/zoom/2"
                
                filter_str = f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s={width}x{height}:fps={fps}"
                
                subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(win_start), "-i", video_path, "-t", str(seg_duration),
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-pix_fmt", "yuv420p",
                    seg_file
                ], check=True, capture_output=True)
                segment_files.append(seg_file)
            
            last_end = win_end
        
        # Final normal segment
        if last_end < duration:
            seg_file = os.path.join(tmpdir, f"seg_{len(segment_files):03d}_norm.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path,
                "-ss", str(last_end), "-to", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                seg_file
            ], check=True, capture_output=True)
            segment_files.append(seg_file)
        
        # Concatenate
        if not segment_files:
            print("No segments!")
            return
        
        concat_file = os.path.join(tmpdir, "concat.txt")
        with open(concat_file, "w") as f:
            for sf in segment_files:
                f.write(f"file '{sf}'\n")
        
        output_path = video_path.replace(".mp4", "_zoomed.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            output_path
        ], check=True, capture_output=True)
        
        print(f"✅ Done: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python apply_zoom.py video.mp4 events.json [sync_offset_sec]")
        sys.exit(1)
    offset = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
    main(sys.argv[1], sys.argv[2], offset)