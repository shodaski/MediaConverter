MEDIA CONVERTER by Zakariae (Shodaski)
======================================

MAKE THE INSTALLER
  1. Install Python (python.org, tick "Add Python to PATH").
  2. Double-click BUILD_INSTALLER.bat  (internet on, takes a few minutes).
  3. Result: Output\MediaConverter_Setup.exe  (+ Output\version.json for updates)

SEND UPDATES TO USERS (automatic, like pro apps)
  One-time setup:
   a. Create a free GitHub account + a public repository (e.g. MediaConverter).
   b. Put the link of your version.json file in media_converter.py, line:
        UPDATE_URL = "https://raw.githubusercontent.com/shodaski/MediaConverter/main/version.json"
   c. Build, and give users this first installer.

  Every new update:
   1. Change the number in version.txt (1.0 -> 1.1), make your changes, run BUILD_INSTALLER.bat.
   2. Upload Output\MediaConverter_Setup.exe to a GitHub "Release" and copy its download link.
   3. Open Output\version.json, paste the link in "url", write "notes", and upload it
      to the repository (replace the old version.json).
   4. Users get "Update available" the next time they open the app. One click and it updates.
