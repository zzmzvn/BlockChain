# Ứng Dụng Bình Chọn

Đây là một ứng dụng bình chọn dựa trên blockchain cho phép người dùng tạo các cuộc thăm dò, bỏ phiếu và xem kết quả. Ứng dụng sử dụng Flask cho backend và kết nối với mạng blockchain để lưu trữ và xác minh các phiếu bầu.

## Tính Năng

- Tạo và quản lý các cuộc thăm dò
- Bỏ phiếu cho các cuộc thăm dò đang hoạt động
- Xem kết quả thăm dò
- So sánh kết quả giữa blockchain và cơ sở dữ liệu SQL

## Cài Đặt

1. **Clone kho lưu trữ:**

   ```bash
   git clone <repository-url>
   cd Vote
   ```

2. **Cài đặt các phụ thuộc:**

   Đảm bảo bạn đã cài đặt Python và pip, sau đó chạy:

   ```bash
   pip install -r requirements.txt
   ```

3. **Cấu hình ứng dụng:**

   Cập nhật file `config.json` với các chi tiết cấu hình cụ thể của bạn, chẳng hạn như URL mạng blockchain và đường dẫn file cơ sở dữ liệu.

4. **Chạy ứng dụng:**

   ```bash
   python backend/VottingApp.py
   ```

5. **Truy cập ứng dụng:**

   Mở trình duyệt web của bạn và truy cập `http://localhost:<port>` để sử dụng ứng dụng.

## Tổng Quan Mã Nguồn

- **backend/VottingApp.py**: File ứng dụng chính chứa các route và logic để tương tác với blockchain và cơ sở dữ liệu.
- **templates/**: Chứa các mẫu HTML để render các trang web.
- **config.json**: File cấu hình để thiết lập ứng dụng.

## Ảnh Chụp Màn Hình

![Bảng Điều Khiển](People/dashboard.jpg)
*Mô tả về hình ảnh bảng điều khiển.*


![KKết Quả giao dịch](Ganache.jpg)
*Mô tả về hình ảnh so sánh kết quả.*
## Giấy Phép

Dự án này được cấp phép theo Giấy phép MIT. 
