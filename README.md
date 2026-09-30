# PMS--AI-Project-Managmant-System-
A full-stack Project Management System REST API built with Django &amp; Django REST Framework.  Features JWT authentication, project tracking, task assignment, team management,  comments, and notifications.
# 📋 Project Management System (PMS) API

A robust and scalable **Project Management System REST API** built with **Django** and **Django REST Framework**. Designed for teams to manage projects, tasks, members, comments, and notifications — all secured with JWT authentication.

---

## 🚀 Features

- 🔐 **JWT Authentication** — Register, Login, Logout, Token Refresh
- 📁 **Project Management** — Create, update, soft-delete projects
- ✅ **Task Management** — Assign tasks, track status and priority
- 👥 **Team Members** — Manage team profiles, skills, and experience
- 💬 **Comments** — Comment on tasks, pin important comments
- 🔔 **Notifications** — Per-user notifications with read/unread tracking
- 🔗 **Project Teams** — Link projects, tasks, and team members together
- 🗑️ **Soft Delete** — No data is permanently lost

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.14 |
| Framework | Django 6.0 |
| API | Django REST Framework |
| Authentication | JWT (djangorestframework-simplejwt) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| API Testing | Postman |

---

## 📁 Project Structure

```
pms/
├── pms/                  # Project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── pms_app/              # Main application
│   ├── models.py         # Database models
│   ├── serializers.py    # DRF serializers
│   ├── views.py          # API views
│   ├── urls.py           # URL patterns
│   └── migrations/       # Database migrations
├── manage.py
└── requirements.txt
```

---

## ⚙️ Installation & Setup

**1. Clone the repository**
```bash
git clone https://github.com/saifulazeem/pms.git
cd pms
```

**2. Create and activate virtual environment**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure settings**

Add to `settings.py`:
```python
AUTH_USER_MODEL = 'pms_app.User'

INSTALLED_APPS = [
    ...
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'pms_app',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

from datetime import timedelta
SIMPLE_JWT = {
    'USER_ID_FIELD': 'u_id',
    'USER_ID_CLAIM': 'user_id',
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'BLACKLIST_AFTER_ROTATION': True,
    'ROTATE_REFRESH_TOKENS': True,
}
```

**5. Run migrations**
```bash
python manage.py makemigrations pms_app
python manage.py migrate
```

**6. Create superuser**
```bash
python manage.py createsuperuser
```

**7. Run the server**
```bash
python manage.py runserver
```

API is now live at: `http://127.0.0.1:8000/`

---

## 📌 API Endpoints

### 🔐 Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/auth/register/` | Register new user |
| POST | `/api/auth/login/` | Login and get JWT tokens |
| POST | `/api/auth/logout/` | Logout and blacklist token |
| POST | `/api/auth/token/refresh/` | Refresh access token |
| GET | `/api/auth/me/` | Get current user profile |
| PATCH | `/api/auth/me/` | Update current user profile |

### 👤 Users
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/users/` | List all users |
| GET | `/api/users/<u_id>/` | Get user by ID |
| PATCH | `/api/users/<u_id>/` | Update user |
| DELETE | `/api/users/<u_id>/` | Soft-delete user |

### 📁 Projects
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/projects/` | List all projects |
| POST | `/api/projects/` | Create project |
| GET | `/api/projects/<p_id>/` | Get project detail |
| PATCH | `/api/projects/<p_id>/` | Update project |
| DELETE | `/api/projects/<p_id>/` | Soft-delete project |
| GET | `/api/projects/<p_id>/tasks/` | Get all tasks in project |

### ✅ Tasks
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/tasks/` | List tasks (filterable) |
| POST | `/api/tasks/` | Create task |
| GET | `/api/tasks/<t_id>/` | Get task detail |
| PATCH | `/api/tasks/<t_id>/` | Update task |
| DELETE | `/api/tasks/<t_id>/` | Soft-delete task |
| GET | `/api/tasks/<t_id>/comments/` | Get all comments on task |

### 👥 Team Members
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/team-members/` | List all team members |
| POST | `/api/team-members/` | Add team member |
| GET | `/api/team-members/<Tm_id>/` | Get member detail |
| PATCH | `/api/team-members/<Tm_id>/` | Update member |
| DELETE | `/api/team-members/<Tm_id>/` | Soft-delete member |

### 💬 Comments
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/comments/` | List all comments |
| POST | `/api/comments/` | Add comment |
| GET | `/api/comments/<c_id>/` | Get comment detail |
| PATCH | `/api/comments/<c_id>/` | Edit comment (owner only) |
| DELETE | `/api/comments/<c_id>/` | Delete comment (owner only) |
| PATCH | `/api/comments/<c_id>/pin/` | Toggle pin on comment |

### 🔔 Notifications
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/notifications/` | Get my notifications |
| PATCH | `/api/notifications/read-all/` | Mark all as read |
| GET | `/api/notifications/<n_id>/` | Get one notification |
| PATCH | `/api/notifications/<n_id>/read/` | Mark one as read |
| DELETE | `/api/notifications/<n_id>/delete/` | Soft-delete notification |

### 🔗 PTeam
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/pteam/` | List all assignments |
| POST | `/api/pteam/` | Create assignment |
| GET | `/api/pteam/<pt_id>/` | Get assignment detail |
| DELETE | `/api/pteam/<pt_id>/` | Remove assignment |

---

## 🔑 Authentication

All endpoints except `register` and `login` require a JWT token.

**Login to get token:**
```json
POST /api/auth/login/
{
  "email": "ahmed@test.com",
  "password": "test1234"
}
```

**Use token in requests:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 📦 Requirements

```
Django>=6.0
djangorestframework>=3.15
djangorestframework-simplejwt>=5.3
```

Generate full requirements file:
```bash
pip freeze > requirements.txt
```

---

## 🗄️ Database Models

| Model | Description |
|---|---|
| `User` | Custom user with email login |
| `Project` | Main project container |
| `Task` | Work unit under a project |
| `TeamMember` | Team member profile |
| `PTeam` | Project-Task-Member junction |
| `Comment` | Task comments |
| `Notification` | User notifications |

---

## 👨‍💻 Developer

**Muhammad Saif Ul Azeem Abbasi**
Senior Software Engineer — R&D Center, Prince Sattam Bin Abdulaziz University

- GitHub: [@saifulazeem](https://github.com/saifulazeem)
- LinkedIn: [muhammad-saif-ul-azeem-abbasi](https://linkedin.com/in/muhammad-saif-ul-azeem-abbasi-1b71b417a)

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
