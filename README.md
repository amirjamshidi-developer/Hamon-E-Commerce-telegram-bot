
# 🤖 Telegram Bot Backend

A production-ready Telegram bot backend built with **Python 3.11** and **Aiogram 3.x**, designed for authentication, order tracking, and customer support automation such as request repair for POS machine device, submit complaints and etc.

---

## ✨ Features

- 🔐 User authentication via National ID (also include entity)
- 📦 Order tracking (by reception number or serial of device)
- 💬 Complaint and repair request submission
- 🛠️ Admin notification system
- 🔄 Redis-based session & FSM state management
- 📊 Metrics and monitoring support
- 🐳 Fully Dockerized deployment

---
## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Telegram Bot Token
- API server credentials

### Installation

#### 1. Clone the repo

```bash
git clone https://github.com/Amirelvx11/Hamon-E-Commerce-telegram-bot.git

# move to main root of project
cd Hamon-E-Commerce-telegram-bot
```
#### 2. Setup environment
create enviroment files based on your telegram token, auth token,server and redis url and etc.
```bash
cp .env.example .env
```
#### Note: Edit .env with your credentials

#### 3. Run with Docker
```bash
docker-compose up -d --build
```
#### 4. Check logs 
```bash
docker-compose logs -f bot
```

### 📁 Project Structure
## src/

### ├── config/ # Settings & enums
### ├── core/ # Bot manager, Redis, Client & etc.
### ├── services/ # API & Notification logic
### ├── handlers/ # Message & Callback routing
### └── utils/ # Helpers & templates

### ⚙️ Configuration
Required Variables
```
.env 
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_CHAT_ID=your_chat_id
API Endpoints
API_BASE_URL=https://api.example.com
NATIONAL_ID=https://api.example.com/nid
ORDER_BY_NUMBER=https://api.example.com/order/number
ORDER_BY_SERIAL=https://api.example.com/order/serial

#Redis
REDIS_URL=redis://redis:6379/1

#Features
MAINTENANCE_MODE=false
```
### 🐳 Docker Commands
```bash
#Start
docker-compose up -d --build

#Logs
docker-compose logs -f bot

#Restart
docker-compose restart bot

#Clean restart
docker-compose down -v && docker-compose up -d --build
```
### 🧪 Development
Local Setup
```bash
# create virtual enviroment
python -m venv venv

# activate venv
source venv/bin/activate

# install dependencies
pip install -r requirements.txt

# run project
python main.py
```
### File Organization
#### Config: /src/config/
#### Core: /src/core/
#### Handlers: /src/handlers/
#### Services: /src/services/
#### Utils: /src/utils/
### 📊 Monitoring
- Basic logging (INFO/ERROR)
- Admin alerts for errors
- Health checks via API
### 🛠️ Tech Stack
- Component	Tool
- Framework	Aiogram 3.x
- Runtime	Python 3.11
- Cache	Redis 7.x
- HTTP Client	aiohttp
- Container	Docker
### 🔒 Security
- Environment secrets
- Input validation
- Session encryption
### 📝 License
MIT License - see LICENSE

### 🤝 Contributing
- Fork the repo
- Create a feature branch
- Submit a PR
- Follow PEP 8, test changes, and document functions.

### 📞 Support
- Issues: GitHub Issues
- GitHub: [@Amirelvx11].com/Amirelvx11)
### 🙏 Acknowledgments
- Aiogram
- Redis
- Docker

