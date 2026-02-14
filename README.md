# 🎧 Eudic Auto Uploader

**Eudic Auto Uploader** is a comprehensive Python automation tool designed to streamline the workflow of managing audio content for the "Eudic" (每日英语听力) platform.

It automatically fetches audio episodes from specified RSS feeds (BBC, CNN, Apple News, etc.) and uploads them to the Eudic backend using browser automation. This tool handles the entire pipeline: downloading, filename sanitization, de-duplication, and batch uploading with AI subtitle support.

---

## ✨ Key Features

* **📡 RSS Auto-Fetching**: Automatically parses RSS feeds defined in `rss_config.yaml` and downloads the latest episodes based on your criteria.
* **🧹 Smart Filename Sanitization**: Automatically cleans special characters from filenames to prevent server-side encoding errors (乱码) and extraction failures.
* **🧠 Intelligent Uploading**:
    * **Single File Mode**: Automatically enables "AI Subtitles" and checks necessary agreements.
    * **Batch Mode**: Automatically packages multiple files into a ZIP archive for faster bulk uploading.
* **🤖 Browser Automation**: Uses Microsoft Playwright to simulate real user interactions, ensuring stability.
* **📂 Local Directory Scanning**: Supports "What You See Is What You Upload" by scanning local folders directly—no database dependency required.
* **🛡️ Fault Tolerance**: Built-in retry logic and error handling to prevent the script from crashing during network fluctuations.

---

## 🛠️ Prerequisites

* **Python 3.8+**
* **Chrome / Chromium Browser** (Managed by Playwright)

---
