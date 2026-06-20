# 💎 RoboxPipeline — Your Roblox TikTok Robot

This is a **robot helper** that finds cool Roblox games, gives them a score,
makes TikTok videos about them, and learns what gets you more followers.

You stay the boss: the robot does the hard work, you just say *"yes, post this"*
and put the video on TikTok.

This guide is written for someone who has **never used a computer for this kind
of thing before**. Follow each step exactly. You cannot break anything.

---

## 🧰 What you need first (3 things)

You only have to get these **one time**.

### 1. An Anthropic AI key
This is like a password that lets the robot write game ratings.
- Go to **https://console.anthropic.com** in your web browser.
- Make an account (it gives you a little free money to start).
- Find the page called **"API Keys"** and click **"Create Key."**
- It gives you a long code that starts with `sk-ant-`. **Copy it and keep it
  somewhere safe** (like a sticky note). You'll paste it in later.

### 2. Python
This is the engine the robot runs on.
- Go to **https://www.python.org/downloads/**
- Click the big yellow **Download** button. Open the file and install it.
- 🪟 **If you're on Windows:** during install, tick the little box that says
  **"Add Python to PATH"** before clicking Install. This is important!

### 3. ffmpeg (the video maker)
- **Mac:** open the Terminal (we explain how below) and type:
  `brew install ffmpeg` then press Enter. *(If `brew` isn't found, first install
  it from https://brew.sh — copy the command on their homepage.)*
- **Windows:** the easiest path is the **Docker method** at the bottom of this
  guide — it includes ffmpeg for you.

> 🙂 Don't worry if this part feels confusing. If you skip ffmpeg, the robot
> still makes the **pictures and captions** — just not the videos yet. You can
> add it anytime.

---

## 🖥️ Step 1: Open the "command box"

The command box is a window where you type instructions. It has different names:

### On a Mac:
1. Hold the **Command (⌘)** key and tap the **Space bar** at the same time.
2. A little search box appears. Type the word **Terminal**.
3. Press **Enter**. A plain window opens. That's the command box. ✅

### On Windows:
1. Click the **Start** button (the Windows logo, bottom-left of your screen).
2. Type the word **PowerShell**.
3. Click **Windows PowerShell** in the results. A blue window opens. ✅

Leave this window open. You'll type into it in the next steps.

---

## 📂 Step 2: Go into the project folder

The robot's files are in a folder called `tiktok-robox`. You need to tell the
command box to "go inside" that folder.

1. In the command box, type this exactly (including the space after `cd`):

   ```
   cd 
   ```

   ⚠️ Don't press Enter yet! Type `cd` and **one space**.

2. Now **drag the `tiktok-robox` folder** from your Desktop (or wherever it is)
   and **drop it right onto the command box window**. The folder's location
   appears automatically. Magic. ✨

3. **Now** press **Enter**.

You're now "inside" the folder. 

---

## 🚀 Step 3: Run the magic setup command

Copy this **one line**, paste it into the command box, and press **Enter**:

```
bash quickstart.sh
```

> 📋 **How to paste:** on Mac press **Command + V**. On Windows, **right-click**
> inside the window.

That's it! The robot now sets everything up by itself. It will:
- ✅ check Python and ffmpeg
- ✅ install all its parts (this takes a few minutes — that's normal)
- ✅ **ask you to paste your `sk-ant-` key** → paste it and press Enter
- ✅ ask *"make your first videos now?"* → just press **Enter** for yes
- ✅ open your control panel

When it's done, you'll see a message pointing you to a web address. 👇

---

## 🌐 Step 4: Open your control panel

1. Open your web browser (Chrome, Safari, Edge — any of them).
2. In the address bar at the top, type this and press Enter:

   ```
   localhost:8000
   ```

3. Your control panel appears! 🎉 This is where you run everything from now on —
   no more typing commands needed.

---

## 📱 Step 5: Make and post a video (your daily routine)

On the control panel website:

1. **Click "Queue"** at the top. You'll see cards — one per game — each with a
   score, two poster designs, and a caption.

2. **Pick one you like** and click the green **Approve** button.
   *(Click ✗ to skip ones you don't like.)*

3. Click the approved card → **"Get Post Package."** Here you can:
   - ⬇️ **Download the video**
   - 📋 **Copy the caption** (one click — hashtags are included)
   - 🖼️ Save one of the two posters

4. **Open TikTok** (on your phone or computer), upload the video, paste the
   caption, and post it. *(The robot can't touch TikTok itself — that's the
   rule, so you do this part.)*

5. Come back to the website and click **"Mark as Posted."**

That's one video! Do this **a few times a day**. 🔁

---

## 🧠 Step 6: Help the robot get smarter

The day after you post, your video will have some numbers on TikTok (views,
likes, new followers).

1. On the control panel, click **"Analytics."**
2. Fill in the simple form: how many views, likes, follows, etc.
3. Click **Submit.**

The robot reads these and learns *"people loved that kind of game — find more
like it!"* Every day you do this, its picks get better. 🌟

---

## 🛑 How to stop and start again

- **To stop the robot:** go back to the command box and hold the **Control**
  key and press **C**.
- **To start it again another day:** open the command box, do Step 2 (go into
  the folder), then type `bash quickstart.sh` and press Enter. It remembers
  everything — it'll skip the setup and jump straight to your control panel.

---

## 🎯 The goal

Post a few videos every day and log your numbers. Keep going, and the followers
add up — the target is **10,000 followers in 30 days**. The control panel home
page shows a progress bar so you can watch it climb. 📈

---

## 🆘 If something goes wrong

| What you see | What to do |
|---|---|
| "Python is not installed" | Do thing #2 in "What you need first." On Windows, remember the "Add to PATH" box. |
| The robot's posters look plain/ugly | Fonts are missing. Mac: `brew install` is fine. Linux: run `sudo apt install fonts-liberation`. The Docker method fixes this automatically. |
| Videos don't get made | ffmpeg isn't installed (thing #3). |
| "ANTHROPIC_API_KEY" error | Your key wasn't saved. Run `bash quickstart.sh` again and paste it when asked. |
| The queue is empty | On the home page, click **"Run Discovery,"** then **"Generate Content."** |
| Website won't open | Make sure the command box still shows it running. If you stopped it, run `bash quickstart.sh` again. |

---

## 🐳 Windows shortcut: the Docker method (optional, all-in-one)

If the steps above feel like too much on Windows, this bundles everything
(Python, ffmpeg, fonts) into one package.

1. Install **Docker Desktop** from https://www.docker.com/products/docker-desktop
2. Open the `tiktok-robox` folder. Find the file named **`.env.example`**,
   make a **copy** of it, and rename the copy to just **`.env`**.
3. Open that `.env` file with **Notepad**. Find the line
   `ANTHROPIC_API_KEY=sk-ant-...` and replace the `sk-ant-...` part with your
   real key. Save and close.
4. Open the command box (PowerShell), go into the folder (Step 2 above), and type:
   ```
   docker-compose up -d
   ```
5. Open your browser to **localhost:8000**. Done!

---

## 🤓 For advanced users

If you know your way around a terminal, you don't need the quickstart script:

```bash
pip install -r requirements.txt        # install
python scripts/init_db.py              # set up the database
python main.py discover                # crawl Roblox
python main.py generate 20             # make content for top 20 games
python main.py serve                   # dashboard at :8000
```

Architecture, scoring model, and the analytics feedback loop are documented in
the source under `src/`. Tests: `pytest tests/`.

---

**Remember:** you can't break anything. If you get stuck, just close the command
box, reopen it, and start from Step 2 again. 💪
