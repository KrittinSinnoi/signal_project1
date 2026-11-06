import sys
import struct
from collections import deque
import numpy as np
import serial

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QFrame, QProgressBar
)
from PyQt5.QtCore import QTimer, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# ================= ตั้งค่าระบบรับข้อมูล (INMP441 -> MAX 10 FPGA -> ESP32-S3 UNO) =================
SERIAL_PORT = 'COM9'       # เปลี่ยนให้ตรงกับพอร์ต COM ของบอร์ด ESP32-S3 UNO ใน Device Manager
BAUD_RATE = 921600         # ความเร็ว Serial (ตรงกับ SERIAL_BAUD ในโค้ด ESP32-S3)
FS = 15943.88              # Sampling Rate จริงจากวงจร I2S ของ FPGA (50 MHz / (49 * 64))
BLOCK_SIZE = 1024          # ขนาดบล็อก N = 1024 ตัวอย่าง
SIMULATION_MODE = False    # True = โหมดจำลอง (ไม่เปิดพอร์ต Serial เลย), False = รับข้อมูลจริงจาก ESP32-S3
MIN_RMS = 3.0              # เกณฑ์ความดังขั้นต่ำ (เดิม 20 สูงเกินไปสำหรับ INMP441 >> 11 บิต ทำให้ไม่อัปเดตกราฟ)
SET_DTR = True             # พอร์ต USB native ของ ESP32-S3 ต้องให้ DTR=True ไม่งั้นบางโหมดจะไม่ส่งข้อมูลออกมา
FRAME_LEN = 2 + BLOCK_SIZE * 2

# ================= ตั้งค่าการลด Noise / ตรวจจับความถี่ (ส่วนที่เพิ่ม) =================
ANALYSIS_N    = 4096       # ต่อ 4 บล็อกล่าสุด -> ความละเอียด FS/4096 = 3.9 Hz (เดิม 15.6 Hz)
NFFT          = 16384      # Zero-padding 4 เท่า -> หายอดได้ละเอียดขึ้น
F_LO, F_HI    = 60.0, 1000.0   # ช่วงค้นหาความถี่หลัก (Fundamental)
N_HARM        = 6          # จำนวน Harmonic ที่ใช้ยืนยันโน้ต (กันอ่านผิด octave)
SNR_MIN_DB    = 12.0       # ยอดต้องสูงกว่า noise floor อย่างน้อยเท่านี้ ถึงจะนับเป็นเสียงจริง
OVERSUB       = 2.0        # Spectral subtraction: ลบ noise 2 เท่าของที่ประมาณได้
MEDIAN_BINS   = 61         # ความกว้าง median filter ตามแกนความถี่ (~60 Hz) สำหรับหา noise floor
NOISE_LEARN_S = 1.5        # วินาทีแรกหลังเปิดโปรแกรม: เรียนรู้ noise ห้อง/ไฟจี่ (ให้เงียบไว้)
NOISE_ADAPT   = 0.05       # อัปเดต noise ต่อเนื่องเฉพาะตอนที่ไม่มีโน้ต
MEDIAN_LEN    = 5          # Median ตามเวลาของความถี่ที่วัดได้ (ตัดค่ากระโดด)
JUMP_CENTS    = 50.0       # ต่างจากค่าเดิมเกินนี้ = เปลี่ยนโน้ตใหม่
CHORD_WINDOW_CENTS = 150.0   # โหมด Auto: ค้นหารอบโน้ตแต่ละสาย ±150 cents (สายในคอร์ดห่างกัน ≥ 300 cents)
LOCK_WINDOW_CENTS  = 350.0   # โหมดเลือกสาย: ค้นหารอบโน้ตเป้าหมาย ±350 cents (จับสายที่เพี้ยนมากได้)
HARM_AGREE_CENTS   = 25.0    # harmonic ต้องให้ f0 ตรงกันภายในเท่านี้ ถึงนับว่าเป็นสายเดียวกัน
B_MAX              = 8e-4    # ค่า inharmonicity สูงสุดของสายกีตาร์ที่ยอมรับ
PLOT_F_TOP    = 2100.0     # คำนวณ/วาดสเปกตรัมถึงความถี่นี้ (กราฟแสดง 50-750 Hz เหมือนเดิม)

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# ตารางแมปค่า Slide Switch (SW0-SW4) ของบอร์ด FPGA MAX 10 เข้ากับคอร์ดและโน้ตแต่ละสาย (MIDI Note)
FPGA_SWITCH_CHORDS = {
    0: {"name": "SW = OFF (Chromatic Auto)", "midis": None},
    1: {"name": "SW(0) = ON : คอร์ด C (C2 G2 C3 G3 C4 E4)",    "midis": [36, 43, 48, 55, 60, 64]},
    2: {"name": "SW(1) = ON : คอร์ด D (D2 A2 D3 F#3 A3 D4)",   "midis": [38, 45, 50, 54, 57, 62]},
    3: {"name": "SW(2) = ON : คอร์ด E (E2 B2 E3 G#3 B3 E4)",   "midis": [40, 47, 52, 56, 59, 64]},
    4: {"name": "SW(3) = ON : คอร์ด F (F2 A2 C3 F3 C4 F4)",    "midis": [41, 45, 48, 53, 60, 65]},
    5: {"name": "SW(4) = ON : Standard Tuning (E2 A2 D3 G3 B3 E4)", "midis": [40, 45, 50, 55, 59, 64]}
}

def midi_to_freq(midi_num):
    return 440.0 * (2 ** ((midi_num - 69) / 12.0))

def midi_to_name(midi_num):
    name = NOTE_NAMES[midi_num % 12]
    octave = (midi_num // 12) - 1
    return f"{name}{octave}"


class FPGATunerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("INMP441 + MAX 10 FPGA + ESP32-S3 Real-Time Chord FFT Tuner (PyQt5)")
        self.resize(1080, 860)
        self.setStyleSheet("background-color: #1e1e2f; color: #ffffff;")

        self.pitch_history = deque(maxlen=50)
        self.sim_phase = 0.0
        self.sim_switch_code = 1   # ค่าเริ่มต้นจำลองว่าสับสวิตช์ SW(0) = คอร์ด C
        self.current_sw_code = -1
        self.locked_midi = None
        self.ser = None
        self.rxbuf = bytearray()
        self.frames_ok = 0
        self.last_rms = 0.0

        self.chord_fft_lines = {}
        self.chord_fft_texts = {}
        self.init_dsp()

        if not SIMULATION_MODE:
            try:
                self.ser = serial.Serial(
                    port=SERIAL_PORT,
                    baudrate=BAUD_RATE,
                    timeout=0.02,
                    rtscts=False,
                    dsrdtr=False
                )
                # ป้องกันไม่ให้ ESP32-S3 รีเซ็ตค้างตอนเปิดพอร์ต
                self.ser.rts = False
                self.ser.dtr = SET_DTR
                self.ser.reset_input_buffer()
                print(f"Connected to ESP32-S3 on {SERIAL_PORT} at {BAUD_RATE} baud.")
            except Exception as e:
                print(f"Serial Error: {e} -> Switching to Simulation Mode")
                self.ser = None

        if self.ser is None:
            self.learn_left = 0      # โหมดจำลองมีเสียงตลอด -> ไม่ต้องเรียนรู้ noise ตอนเริ่ม

        self.init_ui()
        self.update_chord_from_fpga(1)

        # ตั้งเวลาอัปเดตหน้าจอแบบ Non-blocking ทุก 30 ms
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(30)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # ================= 1. แผงแสดงสถานะ Slide Switch จากบอร์ด FPGA MAX 10 =================
        fpga_frame = QFrame()
        fpga_frame.setStyleSheet("background-color: #252538; border: 2px solid #00ffcc; border-radius: 8px; padding: 6px;")
        fpga_layout = QVBoxLayout(fpga_frame)

        self.lbl_fpga_status = QLabel("สถานะสวิตช์ FPGA MAX 10 : รอรับข้อมูล...")
        self.lbl_fpga_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #00ffcc; border: none;")
        fpga_layout.addWidget(self.lbl_fpga_status)

        sw_btn_layout = QHBoxLayout()
        self.sw_buttons = {}
        sw_labels = [
            (0, "All SW OFF (Auto)"),
            (1, "SW(0) = คอร์ด C"),
            (2, "SW(1) = คอร์ด D"),
            (3, "SW(2) = คอร์ด E"),
            (4, "SW(3) = คอร์ด F"),
            (5, "SW(4) = Standard Tuning")
        ]
        for code, text in sw_labels:
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, c=code: self.set_sim_switch(c))
            sw_btn_layout.addWidget(btn)
            self.sw_buttons[code] = btn

        fpga_layout.addLayout(sw_btn_layout)
        main_layout.addWidget(fpga_frame)

        # ================= 2. แผงปุ่มเลือกสายในคอร์ดเพื่อปรับความถี่ให้ตรง =================
        str_frame = QFrame()
        str_frame.setStyleSheet("background-color: #252538; border: 1px solid #555577; border-radius: 8px; padding: 6px;")
        str_vbox = QVBoxLayout(str_frame)

        lbl_str_title = QLabel("เลือกสายในคอร์ดเพื่อปรับความถี่ให้ตรงเส้นเป้าหมายบนกราฟ FFT (เมื่อจูนตรงกัน กราฟ FFT จะเปลี่ยนเป็นสีเขียว):")
        lbl_str_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffcc00; border: none;")
        str_vbox.addWidget(lbl_str_title)

        self.string_btn_layout = QHBoxLayout()
        str_vbox.addLayout(self.string_btn_layout)
        main_layout.addWidget(str_frame)

        # แถบสไลเดอร์จำลองการหมุนลูกบิดปรับความถี่สาย (แสดงเฉพาะตอนเปิดโหมดจำลอง)
        if SIMULATION_MODE or self.ser is None:
            sim_layout = QHBoxLayout()
            lbl_sim = QLabel("จำลองการหมุนลูกบิดปรับความถี่สาย (เลื่อนให้ยอดกราฟ FFT ทับเส้นประของคอร์ด):")
            lbl_sim.setStyleSheet("font-size: 13px; font-weight: bold; color: #ff99cc;")
            self.sim_slider = QSlider(Qt.Horizontal)
            self.sim_slider.setRange(600, 4000) # 60.0 Hz ถึง 400.0 Hz
            self.sim_slider.setValue(1308)      # เริ่มต้นที่ 130.8 Hz (ตรงกับโน้ต C3 ของคอร์ด C)
            sim_layout.addWidget(lbl_sim)
            sim_layout.addWidget(self.sim_slider)
            main_layout.addLayout(sim_layout)

        # ================= 3. หน้าปัดแสดงโน้ตเป้าหมายและแถบวัดความเพี้ยน (Cents) =================
        tuner_frame = QFrame()
        tuner_frame.setStyleSheet("background-color: #2a2a40; border-radius: 10px; padding: 8px;")
        tuner_layout = QVBoxLayout(tuner_frame)

        self.lbl_note = QLabel("เป้าหมาย: --")
        self.lbl_note.setAlignment(Qt.AlignCenter)
        self.lbl_note.setStyleSheet("font-size: 42px; font-weight: bold; color: #00ffcc;")
        tuner_layout.addWidget(self.lbl_note)

        self.lbl_freq = QLabel("ความถี่ที่วัดได้: 0.00 Hz  |  ความถี่เป้าหมาย: 0.00 Hz")
        self.lbl_freq.setAlignment(Qt.AlignCenter)
        self.lbl_freq.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        tuner_layout.addWidget(self.lbl_freq)

        self.cents_bar = QProgressBar()
        self.cents_bar.setRange(0, 100)
        self.cents_bar.setValue(50)
        self.cents_bar.setTextVisible(False)
        self.cents_bar.setFixedHeight(24)
        tuner_layout.addWidget(self.cents_bar)

        self.lbl_advice = QLabel("รอรับสัญญาณเสียงจากไมโครโฟน INMP441...")
        self.lbl_advice.setAlignment(Qt.AlignCenter)
        self.lbl_advice.setStyleSheet("font-size: 15px; font-weight: bold; color: #aaaaaa;")
        tuner_layout.addWidget(self.lbl_advice)

        stats_layout = QHBoxLayout()
        self.lbl_stability = QLabel("Pitch Stability (Std Dev): -- Hz")
        self.lbl_stability.setStyleSheet("font-size: 12px; color: #ffcc00;")
        self.lbl_harmonic = QLabel("2nd/1st Harmonic Ratio: -- %")
        self.lbl_harmonic.setStyleSheet("font-size: 12px; color: #ff6699;")
        self.lbl_harmonic.setAlignment(Qt.AlignRight)
        stats_layout.addWidget(self.lbl_stability)
        stats_layout.addWidget(self.lbl_harmonic)
        tuner_layout.addLayout(stats_layout)

        main_layout.addWidget(tuner_frame)

        # ================= 4. กราฟ FFT Spectrum (พร้อมเส้นความถี่คอร์ด) และ Pitch Stability =================
        self.fig = Figure(figsize=(8, 4.3), facecolor="#1e1e2f")
        self.canvas = FigureCanvas(self.fig)
        self.ax_spec = self.fig.add_subplot(111)

        self.ax_spec.set_facecolor("#14141f")
        self.ax_spec.set_title("Real-Time FFT Spectrum vs. Selected Chord Frequencies (Turns GREEN when In-Tune)", color="white", fontsize=11)
        self.ax_spec.set_xlim(50, 750)
        self.ax_spec.set_ylim(0, 105)
        self.ax_spec.set_xlabel("Frequency (Hz)", color="white")
        self.ax_spec.set_ylabel("Magnitude (dB)", color="white")
        self.ax_spec.tick_params(colors="white")
        self.line_spec, = self.ax_spec.plot([], [], color="#00ccff", lw=2.0)
        self.peak_dots, = self.ax_spec.plot([], [], 'o', color="#ff4444", markersize=8)
        self.fig.tight_layout(pad=2.8)

        main_layout.addWidget(self.canvas)

    def set_sim_switch(self, sw_code):
        self.sim_switch_code = sw_code
        self.update_chord_from_fpga(sw_code)

    def draw_chord_fft_markers(self, midis):
        for line in self.chord_fft_lines.values():
            line.remove()
        for txt in self.chord_fft_texts.values():
            txt.remove()
        self.chord_fft_lines.clear()
        self.chord_fft_texts.clear()

        if midis is not None:
            for m in midis:
                freq = midi_to_freq(m)
                name = midi_to_name(m)
                line = self.ax_spec.axvline(freq, color="#777799", linestyle="--", lw=1.5, alpha=0.8)
                txt = self.ax_spec.text(
                    freq + 4, 88, f"{name}\n({freq:.1f}Hz)",
                    color="#bbbbdd", fontsize=8, fontweight="bold"
                )
                self.chord_fft_lines[m] = line
                self.chord_fft_texts[m] = txt

    def update_chord_from_fpga(self, sw_code):
        if sw_code == self.current_sw_code:
            return
        self.current_sw_code = sw_code
        chord_info = FPGA_SWITCH_CHORDS.get(sw_code, FPGA_SWITCH_CHORDS[0])
        self.lbl_fpga_status.setText(f"สถานะสวิตช์ FPGA MAX 10 ปัจจุบัน :  {chord_info['name']}")

        for code, btn in self.sw_buttons.items():
            if code == sw_code:
                btn.setStyleSheet("background-color: #00ffcc; color: #14141f; font-weight: bold; padding: 6px; border-radius: 5px;")
            else:
                btn.setStyleSheet("background-color: #3a3a52; color: white; padding: 6px; border-radius: 5px;")

        while self.string_btn_layout.count():
            item = self.string_btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.str_buttons = []
        self.locked_midi = None

        btn_auto = QPushButton("Auto (ดึงหาสายที่ใกล้ที่สุดในคอร์ด)")
        btn_auto.clicked.connect(lambda: self.lock_target_string(None, 0))
        self.string_btn_layout.addWidget(btn_auto)
        self.str_buttons.append(btn_auto)

        midis = chord_info["midis"]
        if midis is not None:
            total = len(midis)
            for i, m in enumerate(midis):
                s_num = total - i
                f_val = midi_to_freq(m)
                n_str = midi_to_name(m)
                btn = QPushButton(f"สาย {s_num}: {n_str} ({f_val:.1f} Hz)")
                btn.clicked.connect(lambda checked, midi=m, idx=i+1: self.lock_target_string(midi, idx))
                self.string_btn_layout.addWidget(btn)
                self.str_buttons.append(btn)

        self.draw_chord_fft_markers(midis)
        self.lock_target_string(None, 0)

    def lock_target_string(self, midi_num, btn_idx):
        self.locked_midi = midi_num
        for i, btn in enumerate(self.str_buttons):
            if i == btn_idx:
                btn.setStyleSheet("background-color: #ffcc00; color: #14141f; font-weight: bold; padding: 6px; border-radius: 5px;")
            else:
                btn.setStyleSheet("background-color: #3a3a52; color: white; padding: 6px; border-radius: 5px;")

        if (SIMULATION_MODE or self.ser is None) and midi_num is not None and hasattr(self, 'sim_slider'):
            target_f = midi_to_freq(midi_num)
            self.sim_slider.setValue(int((target_f - 2.5) * 10))
        self.f_hist.clear()

    def read_fpga_block(self):
        if SIMULATION_MODE or self.ser is None:
            t = (np.arange(BLOCK_SIZE) + self.sim_phase) / FS
            self.sim_phase += BLOCK_SIZE
            base_freq = self.sim_slider.value() / 10.0
            f_sim = base_freq + 0.15 * np.sin(2 * np.pi * 0.5 * (self.sim_phase / FS))
            # จำลองข้อมูลเสียง Signed 12-bit จากไมโครโฟน INMP441 (-2048 ถึง +2047)
            # สะสมเฟสต่อเนื่อง (เดิมใช้ t สัมบูรณ์ ทำให้ความถี่จำลองเพี้ยนมากขึ้นเรื่อย ๆ ตามเวลา)
            ph = getattr(self, 'sim_acc', 0.0) + 2 * np.pi * f_sim * np.arange(BLOCK_SIZE) / FS
            self.sim_acc = float((ph[-1] + 2 * np.pi * f_sim / FS) % (2 * np.pi))
            signal = 1200 * np.sin(ph) + 450 * np.sin(2 * ph)
            noise = np.random.normal(0, 20, BLOCK_SIZE)
            self.push_samples(signal + noise)
            return self.sim_switch_code, signal + noise
        else:
            # อ่านทุกไบต์ที่ค้างอยู่ แล้วเลือกเฉพาะเฟรมล่าสุด (ไม่ให้ข้อมูลค้างสะสมจนหน่วง)
            n = self.ser.in_waiting
            if n:
                self.rxbuf.extend(self.ser.read(n))
            if len(self.rxbuf) > FRAME_LEN * 8:          # กันบัฟเฟอร์โตไม่หยุด
                del self.rxbuf[:-FRAME_LEN * 2]

            latest = None
            while True:
                i = self.rxbuf.find(b'\xaa\x55')
                if i < 0:
                    del self.rxbuf[:-1]                  # เก็บไบต์สุดท้ายไว้เผื่อเป็น 0xAA
                    break
                if len(self.rxbuf) - i < FRAME_LEN:
                    del self.rxbuf[:i]                   # รอให้เฟรมครบ
                    break
                # แปลงข้อมูล Binary 2048 Bytes (Little-Endian uint16)
                words = np.frombuffer(bytes(self.rxbuf[i + 2:i + FRAME_LEN]), dtype='<u2')
                codes = (words >> 12) & 0x0F
                if not np.all(codes == codes[0]):        # header ปลอม (รหัส SW ไม่ตรงกันทั้งเฟรม) -> ทิ้ง
                    del self.rxbuf[:i + 1]
                    continue
                del self.rxbuf[:i + FRAME_LEN]
                # บิต [15:12] = รหัส Slide Switch จากบอร์ด FPGA MAX 10
                sw_code = int(codes[0])
                # บิต [11:0] = ข้อมูลเสียง Signed 12-bit (2's Complement) จากไมค์ INMP441
                raw_12b = (words & 0x0FFF).astype(np.int16)
                signed_samples = np.where(raw_12b >= 2048, raw_12b - 4096, raw_12b).astype(np.float64)
                self.push_samples(signed_samples)        # เก็บทุกเฟรมต่อเนื่องเพื่อวิเคราะห์ 4 บล็อก
                self.frames_ok += 1
                latest = (sw_code, signed_samples)

            if latest is None:
                return None, None
            return latest

    # =====================================================================
    #  DSP ลด Noise + ตรวจจับความถี่แม่นยำ
    #   1) ต่อ 4 บล็อกล่าสุด (4096 จุด) + Hann + zero-pad 16384 -> ความละเอียดสูง
    #   2) Noise floor = max(median ตามแกนความถี่, noise ที่เรียนรู้ตอนเงียบ)
    #      median ตัด noise กว้าง ๆ / ที่เรียนรู้ ตัดไฟจี่ 50-100-150 Hz และ noise คงที่
    #   3) Spectral subtraction + เกณฑ์ SNR -> ไม่นับยอด noise เป็นโน้ต
    #   4) ให้คะแนน harmonic (f, f/2, f/3, f/4) -> แก้อ่านผิด octave เมื่อ 2nd harmonic ดังกว่า
    #   5) Parabolic interpolation บน log power + เฉลี่ยจาก harmonic 1-3
    #   6) Median ตามเวลา -> ตัดค่ากระโดด
    # =====================================================================
    def init_dsp(self):
        self.ring = np.zeros(ANALYSIS_N)
        self.ring_filled = 0
        self.win_a = np.hanning(ANALYSIS_N)
        self.freqs_a = np.fft.rfftfreq(NFFT, 1.0 / FS)
        self.df = FS / NFFT
        self.k_plot = int(PLOT_F_TOP / self.df) + 1
        self.k_max = min(len(self.freqs_a) - 1, int(F_HI * N_HARM * 1.05 / self.df) + MEDIAN_BINS)
        self.k_lo, self.k_hi = int(F_LO / self.df), int(F_HI / self.df)
        self.noise_learned = None
        self.noise_rms = None
        self.learn_acc = []
        self.learn_left = 0 if SIMULATION_MODE else int(NOISE_LEARN_S * FS / BLOCK_SIZE)
        self.f_hist = deque(maxlen=MEDIAN_LEN)
        self.last_target = None

    def push_samples(self, x):
        n = len(x)
        self.ring = np.concatenate((self.ring[n:], x))
        self.ring_filled = min(ANALYSIS_N, self.ring_filled + n)

    def _local_floor(self, pw):
        half = MEDIAN_BINS // 2
        padded = np.pad(pw[:self.k_max + 1], half, mode='edge')
        win = np.lib.stride_tricks.sliding_window_view(padded, MEDIAN_BINS)
        floor = np.median(win, axis=1) * 1.44              # median ของ noise power ≈ 0.69 x ค่าเฉลี่ย
        out = np.full_like(pw, floor[-1])
        out[:self.k_max + 1] = floor
        return out

    def _peak_near(self, f_target, pw, snr_db, tol=0.015):
        k0 = max(1, int(f_target * (1 - tol) / self.df))
        k1 = min(len(pw) - 2, int(np.ceil(f_target * (1 + tol) / self.df)))
        if k1 <= k0:
            return None
        k = k0 + int(np.argmax(pw[k0:k1 + 1]))
        if not (pw[k] >= pw[k - 1] and pw[k] >= pw[k + 1]):
            return None
        a, b, c = 10 * np.log10(pw[k - 1:k + 2] + 1e-30)
        d = a - 2 * b + c
        off = float(np.clip(0.5 * (a - c) / d, -0.5, 0.5)) if d < 0 else 0.0
        return (k + off) * self.df, float(snr_db[k]), k

    def _harmonics_at(self, f_target, w_cents, pw, snr_db):
        """หา harmonic h = 1..N_HARM รอบ h*f_target (±w_cents) แล้วเก็บเฉพาะที่ให้ f0 ตรงกัน"""
        tol = 2 ** (w_cents / 1200.0) - 1
        found = []
        for h in range(1, N_HARM + 1):
            if h * f_target * (1 + tol) > FS / 2 - 50:
                break
            pk = self._peak_near(h * f_target, pw, snr_db, tol)
            if pk is not None and pk[1] >= SNR_MIN_DB:
                found.append((h, pk[0], pk[1], float(pw[pk[2]])))
        if not found:
            return []
        est = np.array([e[1] / e[0] for e in found])
        w = np.array([10 ** (e[2] / 20) for e in found])
        order = np.argsort(est)
        cw = np.cumsum(w[order])
        f_med = est[order][min(np.searchsorted(cw, cw[-1] / 2), len(est) - 1)]   # weighted median
        return [e for e in found if abs(1200 * np.log2((e[1] / e[0]) / f_med)) <= HARM_AGREE_CENTS]

    @staticmethod
    def _fit_f0(found):
        """f0 จาก harmonic โดยชดเชย inharmonicity ของสาย: f_h = h*f0*sqrt(1 + B*h^2)"""
        h = np.array([e[0] for e in found], dtype=float)
        fh = np.array([e[1] for e in found])
        w = np.array([10 ** (min(e[2], 60.0) / 20) for e in found])
        B = 0.0
        if len(np.unique(h)) >= 3:                     # ประมาณ B ด้วย weighted least squares
            y = (fh / h) ** 2
            A = np.vstack([np.ones_like(h), h ** 2]).T * w[:, None]
            coef, *_ = np.linalg.lstsq(A, y * w, rcond=None)
            if coef[0] > 0:
                B = float(np.clip(coef[1] / coef[0], 0.0, B_MAX))
        low = h <= 4
        f_each = fh / (h * np.sqrt(1 + B * h ** 2))
        return float(np.sum(w[low] * f_each[low]) / np.sum(w[low])) if low.any() else float(np.average(f_each, weights=w))

    @staticmethod
    def _harm_score(found):
        return sum(min(e[2] - SNR_MIN_DB, 30.0) + 3.0 for e in found)

    def _comb_f0(self, f_target, w_cents, comb):
        """Harmonic comb: หา f ในช่วง ±w_cents ที่ผลรวมพลังงานของ harmonic 1..N_HARM มากที่สุด"""
        c = np.arange(-w_cents, w_cents + 0.1, 2.0)
        f = f_target * 2 ** (c / 1200.0)
        sc = np.zeros_like(f)
        for h in range(1, N_HARM + 1):
            k = np.rint(h * f / self.df).astype(int)
            ok = k < len(comb)
            sc[ok] += comb[k[ok]]
        i = int(np.argmax(sc))
        return f[i], float(sc[i])

    @staticmethod
    def _coincides(fh, f0_other, cents=30.0):
        j = max(1, int(round(fh / f0_other)))
        return abs(1200 * np.log2(fh / (j * f0_other))) <= cents

    def _detect_strings(self, midis, w_cents, pw, snr_db, comb):
        """เลือกสายที่กำลังดีดจากโน้ตของคอร์ด แล้ววัด f0 ของสายนั้น"""
        cands = []
        for mi in sorted(set(midis)):
            f_c, sc = self._comb_f0(midi_to_freq(mi), w_cents, comb)
            if sc <= 0:
                continue
            found = self._harmonics_at(f_c, 35.0, pw, snr_db)
            if found:
                cands.append({"midi": mi, "f0": self._fit_f0(found), "found": found,
                              "power": sum(e[3] for e in found)})
        if not cands:
            return None
        # แยกสายที่ harmonic ซ้อนกัน (เช่น C2-C3, C2-G3, E2-B2):
        # ดูเฉพาะ harmonic ที่เป็นของสายนั้นสายเดียว (ไม่ทับกับอีกสาย) ถ้าเบากว่าอีกสายเกิน 12 dB
        # = สายนั้นแค่สั่นตาม/เห็นแค่ harmonic ของสายที่ดีดจริง -> ตัดทิ้ง
        drop = set()
        th = 10 ** (-12 / 10)
        for i, a in enumerate(cands):
            for b in cands[i + 1:]:
                ea = max([e[3] for e in a["found"] if not self._coincides(e[1], b["f0"])], default=0.0)
                eb = max([e[3] for e in b["found"] if not self._coincides(e[1], a["f0"])], default=0.0)
                es = max([e[3] for e in a["found"] + b["found"]
                          if self._coincides(e[1], a["f0"]) and self._coincides(e[1], b["f0"])], default=0.0)
                if ea == 0 and eb == 0:
                    continue
                if eb == 0:                                 # harmonic ของ b อยู่ในชุดของ a ทั้งหมด (เช่น C3 ใน C2)
                    drop.add(a["midi"] if ea < th * es else b["midi"])
                elif ea == 0:
                    drop.add(b["midi"] if eb < th * es else a["midi"])
                else:
                    a_weak = ea < th * max(eb, es)
                    b_weak = eb < th * max(ea, es)
                    if a_weak and not b_weak:
                        drop.add(a["midi"])
                    elif b_weak and not a_weak:
                        drop.add(b["midi"])
        keep = [c for c in cands if c["midi"] not in drop] or cands
        best = max(keep, key=lambda c: c["power"])
        # วัด f0 ใหม่โดยไม่ใช้ harmonic ที่ทับกับสายอื่นที่สั่นตาม (ยอดซ้อนกันทำให้ค่าเพี้ยน)
        others = [c["f0"] for c in cands if c is not best]
        clean_h = [e for e in best["found"] if not any(self._coincides(e[1], fo, 40.0) for fo in others)]
        f0 = self._fit_f0(clean_h) if len(clean_h) >= 2 else best["f0"]
        return best["midi"], f0

    def _detect_chromatic(self, band, pw, snr_db):
        """SW OFF: ไม่รู้คอร์ด -> หาโน้ตจากยอดแรงสุด + ให้คะแนน harmonic (f, f/2, f/3, f/4)"""
        fp = self.freqs_a[self.k_lo + int(np.argmax(band))]
        best_found = self._harmonics_at(fp, 30.0, pw, snr_db)
        best_s = self._harm_score(best_found)
        for dv in (2, 3, 4):
            f = fp / dv
            if f < F_LO:
                break
            found = self._harmonics_at(f, 30.0, pw, snr_db)
            sc = self._harm_score(found)
            if sc > best_s * 1.15 and any(e[0] % dv != 0 for e in found):
                best_found, best_s = found, sc
        if not best_found:
            return None
        return None, self._fit_f0(best_found)

    def process_dsp(self, samples, sw_code):
        sig = samples - np.mean(samples)
        self.last_rms = float(np.sqrt(np.mean(sig**2)))
        if self.ring_filled < ANALYSIS_N:
            return None

        x = self.ring - np.mean(self.ring)
        X = np.fft.rfft(x * self.win_a, NFFT)
        pw = (X.real ** 2 + X.imag ** 2) / (ANALYSIS_N ** 2)     # สเกลเดียวกับโค้ดเดิม (|X|/N)

        noise = self._local_floor(pw)
        if self.learn_left > 0:                                  # ช่วงเรียนรู้ noise ตอนเริ่ม
            self.learn_acc.append(pw)
            self.learn_left -= 1
            if self.learn_left == 0:
                self.noise_learned = np.mean(self.learn_acc, axis=0)
                self.noise_rms = float(np.std(x))
                self.learn_acc = []
            return None
        if self.noise_learned is not None:
            noise = np.maximum(noise, self.noise_learned)
        noise = np.maximum(noise, 1e-16)
        snr_db = 10 * np.log10(pw / noise)
        clean = np.maximum(pw - OVERSUB * noise, 0.0)

        if self.last_rms < MIN_RMS:
            return None

        # ---- ยอดแรงสุดในช่วงค้นหาที่ผ่านเกณฑ์ SNR ----
        band = clean[self.k_lo:self.k_hi + 1].copy()
        band[snr_db[self.k_lo:self.k_hi + 1] < SNR_MIN_DB] = 0
        if band.max() <= 0:                                      # ไม่มีโน้ต
            rms_a = float(np.std(x))
            # อัปเดต noise เฉพาะเฟรมที่เงียบจริง (ไม่ใช่ช่วงเปลี่ยนโน้ต/เสียงดังไม่มีโน้ต)
            if self.noise_learned is not None and rms_a < 2.0 * self.noise_rms:
                # ลดลงเร็ว (กรณีเผลอมีเสียงตอนเรียนรู้) / เพิ่มขึ้นช้า (noise ห้องเปลี่ยน)
                rate = np.where(pw < self.noise_learned, 0.3, NOISE_ADAPT)
                self.noise_learned = (1 - rate) * self.noise_learned + rate * pw
                r = 0.3 if rms_a < self.noise_rms else NOISE_ADAPT
                self.noise_rms = (1 - r) * self.noise_rms + r * rms_a
            self.f_hist.clear()
            return None
        # ---- ตรวจจับโดยเทียบกับโน้ตของแต่ละสายในคอร์ดโดยตรง ----
        chord_midis = FPGA_SWITCH_CHORDS.get(sw_code, FPGA_SWITCH_CHORDS[0])["midis"]
        # พลังงานหลังตัด noise (บีบด้วย log) เฉพาะ bin ที่ผ่าน SNR, ขยายยอด ±2 bin สำหรับ harmonic comb
        comp = np.where(snr_db >= SNR_MIN_DB, np.log1p(clean / noise), 0.0)
        comb = np.lib.stride_tricks.sliding_window_view(np.pad(comp, 2), 5).max(axis=1)
        if self.locked_midi is not None:
            det = self._detect_strings([self.locked_midi], LOCK_WINDOW_CENTS, pw, snr_db, comb)
        elif chord_midis is not None:
            det = self._detect_strings(chord_midis, CHORD_WINDOW_CENTS, pw, snr_db, comb)
        else:
            det = self._detect_chromatic(band, pw, snr_db)
        if det is None and (self.locked_midi is not None or chord_midis is not None):
            # สายเพี้ยนไกลเกินช่วงค้นหา -> หาแบบทั่วไป แล้วเทียบกับสายเป้าหมาย / สายที่ใกล้ที่สุดในคอร์ด
            det = self._detect_chromatic(band, pw, snr_db)
            if det is not None:
                mm = 69 + 12 * np.log2(det[1] / 440.0)
                tgt = self.locked_midi if self.locked_midi is not None else min(chord_midis, key=lambda q: abs(mm - q))
                det = (tgt, det[1])
        if det is None:
            self.f_hist.clear()
            return None
        target_midi, f_raw = det

        # ---- Median ตามเวลา (เริ่มใหม่เมื่อเปลี่ยนสาย/เปลี่ยนโน้ต) ----
        if target_midi != self.last_target:
            self.f_hist.clear()
            self.last_target = target_midi
        elif self.f_hist and abs(1200 * np.log2(f_raw / float(np.median(self.f_hist)))) > JUMP_CENTS:
            self.f_hist.clear()
        self.f_hist.append(f_raw)
        f0 = float(np.median(self.f_hist))

        measured_midi = 69 + 12 * np.log2(f0 / 440.0)
        if target_midi is None:                                  # SW OFF: Chromatic
            target_midi = int(round(measured_midi))

        cents = 100 * (measured_midi - target_midi)
        target_freq = midi_to_freq(target_midi)
        full_note = midi_to_name(target_midi)

        pk1 = self._peak_near(f0, pw, snr_db, tol=0.03)
        pk2 = self._peak_near(2 * f0, pw, snr_db, tol=0.03)
        peak_idx = pk1[2] if pk1 else int(round(f0 / self.df))
        h2_idx = pk2[2] if pk2 else min(int(round(2 * f0 / self.df)), self.k_plot - 1)
        h_ratio = np.sqrt(pw[h2_idx] / (pw[peak_idx] + 1e-30)) * 100

        # สเปกตรัมหลังตัด noise (สเกล dB เดียวกับเดิม) ส่งไปวาดกราฟ
        freqs = self.freqs_a[:self.k_plot]
        fft_db = 20 * np.log10(np.sqrt(clean[:self.k_plot]) + 1e-6)

        return freqs, fft_db, f0, target_freq, target_midi, full_note, cents, h_ratio, peak_idx, h2_idx

    def update_loop(self):
        sw_code, samples = self.read_fpga_block()
        if samples is not None:
            self.update_chord_from_fpga(sw_code)

            res = self.process_dsp(samples, sw_code)
            if self.ser is not None:
                # แสดงสถานะการรับข้อมูลบนแถบชื่อหน้าต่าง เพื่อเช็คว่าข้อมูลมาถึงจริง
                self.setWindowTitle(
                    f"FPGA Tuner | frames={self.frames_ok} | SW={sw_code} | RMS={self.last_rms:.1f} "
                    f"| min={samples.min():.0f} max={samples.max():.0f}")
                if res is None:
                    if self.learn_left > 0 or self.ring_filled < ANALYSIS_N:
                        self.lbl_advice.setText("กำลังเรียนรู้ Noise ของห้อง... กรุณาเงียบสักครู่")
                    else:
                        self.lbl_advice.setText(f"ได้รับข้อมูลแล้ว แต่ไม่พบโน้ตที่ชัดเจน / เสียงเบาเกินไป (RMS {self.last_rms:.1f})")
            if res is not None:
                freqs, fft_db, f0, target_freq, target_midi, full_note, cents, h_ratio, p1, p2 = res
                diff_hz = f0 - target_freq

                self.pitch_history.append(f0)
                std_dev = np.std(self.pitch_history) if len(self.pitch_history) > 2 else 0.0

                self.lbl_note.setText(f"โน้ตเป้าหมาย: {full_note}")
                self.lbl_freq.setText(
                    f"ความถี่ที่วัดได้: {f0:.2f} Hz   |   ความถี่เป้าหมาย: {target_freq:.2f} Hz   "
                    f"(ต่างกัน {diff_hz:+.2f} Hz / {cents:+.1f} Cents)"
                )
                self.lbl_stability.setText(f"Pitch Stability (Std Dev): ±{std_dev:.2f} Hz")
                self.lbl_harmonic.setText(f"2nd/1st Harmonic Ratio: {h_ratio:.1f} %")

                bar_val = int(50 + max(-50.0, min(50.0, cents)))
                self.cents_bar.setValue(bar_val)

                # เมื่อจูนตรงภายใน ±4.0 Cents ให้เปลี่ยนกราฟ FFT และเส้นคอร์ดเป็นสีเขียว
                is_in_tune = abs(cents) <= 4.0

                if is_in_tune:
                    color = "#00ff00"
                    fft_line_color = "#00ff00"
                    advice = f"✔ ความถี่ FFT ตรงกับโน้ต {full_note} ({target_freq:.1f} Hz) ของคอร์ดแล้ว! (IN TUNE)"
                elif cents < -4.0:
                    color = "#ffcc00"
                    fft_line_color = "#00ccff"
                    advice = f"▲ ความถี่ต่ำกว่าเส้น {full_note} ({diff_hz:.1f} Hz) -> หมุนขันสายขึ้นให้ยอดกราฟ FFT ทับเส้นประ"
                else:
                    color = "#ff4444"
                    fft_line_color = "#ff6666"
                    advice = f"▼ ความถี่สูงกว่าเส้น {full_note} (+{diff_hz:.1f} Hz) -> หมุนคลายสายลงให้ยอดกราฟ FFT ทับเส้นประ"

                self.lbl_note.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {color};")
                self.lbl_advice.setText(advice)
                self.lbl_advice.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {color};")
                self.cents_bar.setStyleSheet(
                    f"QProgressBar {{ background-color: #14141f; border: 2px solid #555; border-radius: 5px; }} "
                    f"QProgressBar::chunk {{ background-color: {color}; }}"
                )

                for m, line in self.chord_fft_lines.items():
                    txt = self.chord_fft_texts[m]
                    if m == target_midi:
                        line.set_color("#00ff00" if is_in_tune else "#ffcc00")
                        line.set_linewidth(2.8 if is_in_tune else 2.2)
                        line.set_linestyle("-" if is_in_tune else "--")
                        txt.set_color("#00ff00" if is_in_tune else "#ffcc00")
                    else:
                        line.set_color("#555577")
                        line.set_linewidth(1.2)
                        line.set_linestyle("--")
                        txt.set_color("#8888aa")

                self.line_spec.set_data(freqs, fft_db)
                self.line_spec.set_color(fft_line_color)
                self.peak_dots.set_data([freqs[p1], freqs[p2]], [fft_db[p1], fft_db[p2]])
                self.peak_dots.set_color("#00ff00" if is_in_tune else "#ff4444")
                self.canvas.draw_idle()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = FPGATunerWindow()
    win.show()
    sys.exit(app.exec_())