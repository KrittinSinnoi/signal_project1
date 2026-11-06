# 🎸 Real-Time Chord FFT Tuner (INMP441 + MAX 10 FPGA + ESP32-S3 + PyQt5)

โปรเจกต์ระบบตรวจจับความถี่เสียงและช่วยตั้งสายกีตาร์ตามคอร์ดแบบเรียลไทม์ (Real-Time) โดยใช้ไมโครโฟนดิจิทัล **INMP441** ส่งสัญญาณผ่านโปรโตคอล $I^2S$ เข้าสู่บอร์ด **Intel MAX 10 FPGA** เพื่อจัดเก็บลงหน่วยความจำ BRAM พร้อมเข้ารหัสสถานะสวิตช์เลือกคอร์ด จากนั้นส่งข้อมูลผ่าน **SPI** ไปยัง **ESP32-S3** เพื่อส่งต่อให้โปรแกรม GUI บนคอมพิวเตอร์ (พัฒนาด้วย **Python PyQt5**) ประมวลผลสัญญาณดิจิทัล (DSP) และแสดงกราฟสเปกตรัม FFT แบบเรียลไทม์

---

## 🏗️ สถาปัตยกรรมของระบบ (System Architecture)

```text
[ INMP441 Mic ] 
       │ (I2S Protocol: SCK, WS, SD)
       ▼
[ Intel MAX 10 FPGA ]  ◄─── [ Slide Switches (SW0 - SW4) เลือกโหมดคอร์ด ]
  ├─ i2s_rx.vhd (รับข้อมูลเสียงดิจิทัล @ Fs = 15,943.88 Hz)
  ├─ chord_encoder.vhd (เข้ารหัสสถานะสวิตช์ 4-bit)
  └─ bram_spi_slave.vhd (แพ็กข้อมูล 16-bit ลง BRAM 1024 คำ & ส่งออกผ่าน SPI)
       │ (SPI Protocol: SCLK, MISO, MOSI, CS)
       ▼
[ ESP32-S3 UNO ]
  └─ project_signal_esp.ino (อ่านบล็อกข้อมูลจาก FPGA แล้วส่งต่อผ่าน USB Serial)
       │ (UART / USB Serial @ 921600 bps, Frame Header: 0xAA 0x55)
       ▼
[ PC Application (Python PyQt5) ]
  └─ final.py (DSP Noise Reduction, Harmonic Comb, Inharmonicity Fit & Real-Time FFT GUI)
```

---

## 📂 โครงสร้างไฟล์ในโปรเจกต์ (Project Structure)

```text
├── final_project_signal_vhdl/          # โฟลเดอร์โปรเจกต์ Quartus Prime (FPGA VHDL)
│   ├── final_project_signal_vhdl.qpf   # ไฟล์โปรเจกต์ Quartus (Version 20.1 Lite)
│   ├── final_project_signal_vhdl.qsf   # ไฟล์ตั้งค่า Pin Assignment และบอร์ด MAX 10
│   ├── final_project_signal_vhdl.vhd   # Top-Level Entity เชื่อมต่อทุกโมดูลเข้าด้วยกัน
│   ├── i2s_rx.vhd                      # โมดูลรับสัญญาณเสียงดิจิทัล I2S จากไมค์ INMP441
│   ├── chord_encoder.vhd               # โมดูลเข้ารหัสสวิตช์ SW(0)-SW(4) เป็นรหัสคอร์ด 4 บิต
│   ├── bram_spi_slave.vhd              # โมดูล Dual-Port BRAM และ SPI Slave สำหรับส่งข้อมูลบล็อก 1024 ตัวอย่าง
│   └── output_files/
│       └── final_project_signal_vhdl.sof # ไฟล์ Bitstream สำหรับอัปโหลดลงบอร์ด FPGA
│
├── project_signal_esp/                 # โฟลเดอร์โค้ดไมโครคอนโทรลเลอร์ ESP32-S3
│   └── project_signal_esp.ino          # โค้ด Arduino รับข้อมูลผ่าน SPI จาก FPGA ส่งออกทาง Serial
│
└── final.py                            # โปรแกรมหลักบนคอมพิวเตอร์ (PyQt5 GUI + ระบบประมวลผล DSP)
```

---

## ✨ คุณสมบัติเด่น (Key Features)

### 1. ฝั่งฮาร์ดแวร์ FPGA และไมโครคอนโทรลเลอร์
* **ฮาร์ดแวร์รับสัญญาณเสียงความแม่นยำสูง:** สร้างสัญญาณนาฬิกา $I^2S$ จากความถี่หลัก $50\text{ MHz}$ ได้อัตราสุ่มสัญญาณ (Sampling Rate) จริงที่:
  $$F_s = \frac{50\text{ MHz}}{49 \times 64} \approx 15,943.88\text{ Hz}$$
* **ระบบแพ็กข้อมูล 16-bit แบบรวมศูนย์:** รวมข้อมูลสถานะสวิตช์และสัญญาณเสียงไว้ใน Word เดียวขนาด 16 บิต (จำนวน $1024\text{ Samples/Block}$):
  * `Bits [15:12]` : รหัสสถานะสวิตช์เลือกคอร์ด (4-bit Switch Code)
  * `Bits [11:0]` : ข้อมูลเสียงดิจิทัล 12-bit Signed (2's Complement) จากไมโครโฟน INMP441
* **การส่งข้อมูลแบบเฟรมความเร็วสูง:** ESP32-S3 ส่งข้อมูลผ่าน USB Serial ที่ความเร็ว `921600 baud` พร้อม Header ซิงโครไนซ์ `0xAA 0x55` และระบบตรวจสอบความถูกต้องของรหัสสวิตช์ทั้งเฟรม

### 2. ฝั่งประมวลผลสัญญาณดิจิทัล (DSP) บน Python (`final.py`)
* **ความละเอียดทางความถี่สูง:** นำ 4 บล็อกล่าสุดมาต่อกัน ($N = 4096\text{ samples}$) คูณด้วยหน้าต่าง **Hann Window** และทำ **Zero-Padding** เป็น $N_{\text{FFT}} = 16384$ จุด ทำให้ได้ความละเอียดของ Bin ความถี่ละเอียดถึง $\Delta f \approx 0.97\text{ Hz}$
* **ระบบลดสัญญาณรบกวนอัตโนมัติ (Adaptive Noise Reduction):**
  * เรียนรู้ Noise Floor ของห้องและเสียงไฟจี่ ($50/100/150\text{ Hz}$) ในช่วง $1.5\text{ วินาที}$ แรกที่เปิดโปรแกรม และปรับค่าต่อเนื่องเมื่อไม่มีเสียงดนตรี
  * ประยุกต์ใช้ **Median Filter** ตามแกนความถี่ร่วมกับ **Spectral Subtraction** และตั้งเกณฑ์ **SNR ขั้นต่ำ ($12\text{ dB}$)** เพื่อตัดยอดสัญญาณรบกวนออกจากการคำนวณ
* **การตรวจจับความถี่หลักที่แม่นยำและแก้ปัญหาอ่านผิด Octave:**
  * ใช้ **Harmonic Comb** และตรวจสอบความสอดคล้องของฮาร์มอนิกที่ $h = 1 \dots 6$
  * คำนวณชดเชยความเพี้ยนจากความตึงของสายกีตาร์ (**String Inharmonicity**) ตามสมการ:
    $$f_h = h \cdot f_0 \sqrt{1 + B h^2}$$
  * แยกแยะสายที่ถูกดีดจริงออกจากสายข้างเคียงที่สั่นพ้องตาม (Sympathetic Resonance) เมื่อฮาร์มอนิกทับซ้อนกัน
  * ใช้ **Parabolic Interpolation** บนสเกล Log-Power ร่วมกับ **Temporal Median Filter** เพื่อให้นิ่งและแม่นยำ

### 3. ส่วนติดต่อผู้ใช้ (PyQt5 Real-Time GUI)
* อัปเดตโหมดคอร์ดอัตโนมัติตามการสับสวิตช์บนบอร์ด FPGA MAX 10
* สามารถเลือกโหมด **Auto** (ค้นหาสายที่ใกล้เคียงที่สุดในคอร์ด) หรือ **Lock เฉพาะสาย** ที่ต้องการตั้งได้
* แสดงเส้นประตำแหน่งความถี่เป้าหมายของทุกสายในคอร์ดบนกราฟ FFT และ **เปลี่ยนกราฟเป็นสีเขียวทันทีเมื่อจูนตรงภายในเกณฑ์ $\pm 4.0\text{ Cents}$**
* มี **โหมดจำลอง (Simulation Mode)** พร้อมสไลเดอร์จำลองการหมุนลูกบิดกีตาร์ สามารถทดสอบโปรแกรมได้แม้ไม่ได้ต่อบอร์ดจริง

---

## 🎛️ ตารางการทำงานของ Slide Switch บนบอร์ด FPGA MAX 10

| รหัส (Code) | สถานะสวิตช์บน FPGA | โหมดการทำงาน / คอร์ด | โน้ตเป้าหมายแต่ละสาย (สาย 6 $\rightarrow$ สาย 1) |
| :---: | :---: | :--- | :--- |
| `0` | ปิดทุกสวิตช์ (`All OFF`) | **Chromatic Auto** (อิสระทุกตัวโน้ต) | ค้นหาโน้ตดนตรีสากลที่ใกล้ที่สุดอัตโนมัติ |
| `1` | `SW(0) = ON` | **คอร์ด C** | `C2` (`65.4 Hz`), `G2` (`98.0 Hz`), `C3` (`130.8 Hz`), `G3` (`196.0 Hz`), `C4` (`261.6 Hz`), `E4` (`329.6 Hz`) |
| `2` | `SW(1) = ON` | **คอร์ด D** | `D2` (`73.4 Hz`), `A2` (`110.0 Hz`), `D3` (`146.8 Hz`), `F#3` (`185.0 Hz`), `A3` (`220.0 Hz`), `D4` (`293.7 Hz`) |
| `3` | `SW(2) = ON` | **คอร์ด E** | `E2` (`82.4 Hz`), `B2` (`123.5 Hz`), `E3` (`164.8 Hz`), `G#3` (`207.7 Hz`), `B3` (`246.9 Hz`), `E4` (`329.6 Hz`) |
| `4` | `SW(3) = ON` | **คอร์ด F** | `F2` (`87.3 Hz`), `A2` (`110.0 Hz`), `C3` (`130.8 Hz`), `F3` (`174.6 Hz`), `C4` (`261.6 Hz`), `F4` (`349.2 Hz`) |
| `5` | `SW(4) = ON` | **Standard Tuning** (ตั้งสายมาตรฐาน) | `E2` (`82.4 Hz`), `A2` (`110.0 Hz`), `D3` (`146.8 Hz`), `G3` (`196.0 Hz`), `B3` (`246.9 Hz`), `E4` (`329.6 Hz`) |

---

## 🛠️ การติดตั้งและใช้งาน (Installation & Usage)

### 1. การโปรแกรมบอร์ด FPGA (Intel Quartus Prime)
1. เปิดโปรแกรม **Intel Quartus Prime (Lite Edition)**
2. เปิดไฟล์โปรเจกต์ `final_project_signal_vhdl/final_project_signal_vhdl.qpf`
3. เชื่อมต่อบอร์ด **MAX 10 FPGA** เข้ากับคอมพิวเตอร์ผ่าน USB Blaster
4. เปิดเครื่องมือ **Programmer** แล้วอัปโหลดไฟล์ `final_project_signal_vhdl/output_files/final_project_signal_vhdl.sof` ลงสู่บอร์ด

### 2. การอัปโหลดโค้ด ESP32-S3 (Arduino IDE)
1. เปิดไฟล์ `project_signal_esp/project_signal_esp.ino` ด้วยโปรแกรม **Arduino IDE**
2. เลือกบอร์ดเป็น **ESP32S3 Dev Module** (หรือ ESP32-S3 UNO) และเลือกพอร์ตให้ถูกต้อง
3. กด **Upload** เพื่อลงโปรแกรมบนบอร์ด ESP32-S3

### 3. การรันโปรแกรมแสดงผลบนคอมพิวเตอร์ (Python)
1. ติดตั้งไลบรารีที่จำเป็นผ่านคำสั่ง `pip`:
   ```bash
   pip install numpy pyserial PyQt5 matplotlib
   ```
2. ตรวจสอบหมายเลขพอร์ต COM ของบอร์ด ESP32-S3 ใน **Device Manager** แล้วแก้ไขค่าตัวแปรในไฟล์ `final.py` (บรรทัดที่ 15):
   ```python
   SERIAL_PORT = 'COM9'       # เปลี่ยนให้ตรงกับพอร์ต COM ของคุณ
   SIMULATION_MODE = False    # ตั้งเป็น True หากต้องการทดสอบแบบไม่ต้องต่อฮาร์ดแวร์
   ```
3. รันโปรแกรมด้วยคำสั่ง:
   ```bash
   python final.py
   ```
4. **ข้อแนะนำขณะเริ่มรันโปรแกรม:** หลังหน้าต่างโปรแกรมเปิดขึ้นมา ให้เงียบเสียงประมาณ **1.5 วินาที** เพื่อให้โปรแกรมเรียนรู้ระดับ Noise ของห้อง หลังจากนั้นสามารถสับสวิตช์เลือกคอร์ดบนบอร์ด FPGA และดีดสายกีตาร์เพื่อตั้งสายได้ทันที
