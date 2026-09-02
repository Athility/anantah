# Anantah (अनंत) — AI Marketplace & Digital Cataloger for Indian Artisans

**Anantah** ("Infinite") is a full-stack platform designed to empower traditional and marginalized Indian craftspeople (potters, silk weavers, brass artisans, woodcarvers, painters, etc.) by connecting them directly with buyers nationwide. It eliminates digital onboarding barriers using cutting-edge AI automation for image enhancement and multilingual voice cataloging.

---

## 🌟 Key Features

### 🎨 For Artisans (Craftspeople)
- **AI Product Studio**: Upload raw, unedited photos taken on any mobile device. The AI automatically removes messy backgrounds, fixes lighting, enhances sharpness, and balances colors to create studio-quality product images.
- **Multilingual Voice Auto-Cataloger**: Artisans can describe their craft naturally in their native regional language (Hindi, Marathi, Gujarati, Tamil, etc.).
  - **Speech-to-Text**: Converts voice notes to text using Groq Whisper ASR.
  - **Bilingual SEO Generation**: Automatically generates high-converting titles and rich product descriptions in both English and regional scripts (Devanagari, Tamil, etc.) using Groq LLaMA.
- **Listing Management**: View active products, publish new items, track orders, and delete listings.
- **Artisan Communities & Analytics**: Connect with regional craft clusters and monitor shop performance (Launching Soon).

### 🛒 For Buyers & Craft Enthusiasts
- **Authentic Handmade Feed**: Browse verified artisan creations directly from traditional craft clusters across India.
- **Cart & Checkout**: Interactive cart drawer, multi-address management, and secure Razorpay payment gateway integration.
- **Buyer Wishlist**: Save handcrafted items to a personal wishlist from product cards or detail modal views, view and manage saved products in a dedicated Wishlist screen, add items directly to cart, and view compact "Saved for later" reminder cards on the buyer Home page.
- **Artisan Reels & Regional Craft Map**: Watch short behind-the-scenes videos of master artisans at work and explore interactive regional craft maps (Launching Soon).

---

## 📱 Navigation & Design System

- **PC Desktop Navigation Bar**: Features a uniform 5-option navigation strip with a smooth, 0.5-second sliding purple indicator badge that glides seamlessly across active menu items.
- **Mobile Bottom Navigation Pill**: Floating glassmorphic bottom navigation bar with a central elevated button, account slide-up sheet, and safe area bottom clearance ensuring all action buttons remain fully visible and clickable on phone screens.
- **Design Tokens**: Tailored color palette (`--primary-color: #4B286D`, `--primary-light: #F4EFFF`, `--accent-gold: #E5A85A`), custom typography (Outfit, Inter, Playfair Display), and responsive glassmorphism aesthetic.
- **Heritage Craft Gradient**: Deep aubergine/plum (`#4A1D4A` to `#6B2D5C`) transitioning into warm terracotta (`#C1573A` to `#D4694A`) applied across the Cart page total bar and checkout buttons.

---

## 🔒 Security & Session Management

- **Phone OTP Verification**: Phone verification with short-lived 15-minute TTL registration tokens.
- **JWT Authentication & Auto-Refresh**: Uses SimpleJWT. A global `customFetch` client wrapper transparently intercepts `401 Unauthorized` responses, refreshes access tokens via `/api/accounts/login/refresh/`, and retries pending requests seamlessly.
- **OTP Password Reset**: "Forgot Password?" flow allowing users to reset their password using a 4-digit verification code sent to their registered phone number.
- **Account Control**: Account deletion view (`DELETE /api/accounts/me/`) with confirmation overlay modal.
- **Unsaved Changes Safeguard**: Prompts artisans before navigating away from active AI refiner listings with unsaved edits.

---

## 🛠️ Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3, Django 5.0, Django REST Framework (DRF) |
| **Database** | SQLite (Dev) / MySQL (Prod) |
| **Authentication** | SimpleJWT (JWT Access & Refresh Tokens), Django Cache OTP Service |
| **Frontend** | HTML5, Vanilla CSS3 (Custom Properties & Animations), Vanilla JavaScript (ES6+ SPA) |
| **AI Services** | Groq API (Whisper ASR & LLaMA 3 Cataloging), Rembg (Background Removal), OpenCV & Pillow |
| **Payments** | Razorpay Gateway Integration |
| **Monitoring & Analytics** | Sentry SDK (Error Tracking), PostHog / Console Analytics |

---

## 🚀 Getting Started

### 1. Prerequisites & Environment Setup
Ensure Python 3.10+ is installed on your system.

```bash
# Clone the repository
git clone <repository-url>
cd "Anantah 1 feature"

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Database Migrations
```bash
python manage.py migrate
```

### 4. Run Development Server
```bash
python manage.py runserver
```

Open your browser and navigate to `http://127.0.0.1:8000/` to access the application.

---

## 📁 Project Structure

```
├── accounts/               # User authentication, OTP verification, profiles & password reset
├── ai_services/            # Groq Whisper ASR, LLaMA cataloging & image enhancement modules
├── anantah_core/           # Django settings, WSGI/ASGI configuration & Sentry setup
├── cart/                   # Shopping cart models, views, and DRF API endpoints
├── listings/               # Artisan product listings, image upload, and search APIs
├── payments/               # Razorpay order creation and payment signature verification
├── config.js               # Frontend API base URL configuration & global customFetch interceptor
├── index.html              # Main Single Page Application (SPA) structure & script handlers
├── style.css               # Global CSS design system, navigation styles, and mobile responsive rules
├── requirements.txt        # Python package dependencies
└── manage.py               # Django management CLI
```

---

## 📝 Maintenance Note

*Keep this README updated as new features, API endpoints, or architecture enhancements are integrated into the Anantah codebase.*
