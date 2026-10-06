# 🥞 ASCII syrnik by JeusDEV.
Python 3.9+, no dependencies.<br><br>
Run in a terminal with ANSI color support.<br>
Works on Windows, macOS, and Linux.<br>
Oversized models fit the window.<br>
Ctrl+C exits cleanly.<br><br>
Also has interactive mode! (-m | --manual)
# 🔽 Setup
Clone repository:
```
git clone https://github.com/JeusDEV/syrnik.git
```
OR single script:
```
curl -O https://raw.githubusercontent.com/JeusDEV/syrnik/refs/heads/master/syrnik.py
```
# 🍴 Usage
```
python syrnik.py
  # default rotation, ASCII shading

python syrnik.py -p -m -r
  # pixel mode, interactive, reversed movement

python syrnik.py -sc 2 -sp 90 -bg -r
  # big and fast, no background, reversed rotation

python syrnik.py -sy ".:#@" -f 60 -u
  # custom ramp, 60 fps, auto rebuild

python syrnik.py -h
  # show help menu
```
---
⚠ **WARN**:<br>
Please enable (-u | --update-build) to rebuild the model on window resize; useful for long sessions, costs a short rebuild pause.
<br>If it's lagging on window resize check this flag enabled or not.

ℹ **DETAILS**:<br>
If (-p | --pixel) is enabled, custom ramp (-sy | --symbols) has no effect.

If (-m | --manual) is enabled, (-r | --reverse) flips the arrow controls.

Manual mode (-m) requires an interactive terminal on stdin.

---

🤞 **CREDITS**:<br>
Pchelka TV - baseline support<br>
mcKisco - ideas & mastermind<br>
UTK initiative (cheri, cbkzly) - fellas
