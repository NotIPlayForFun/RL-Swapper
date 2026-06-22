## Warning: still in beta (until soon...)

Since I originally created this on a whim using mostly copilot for my own use before deciding it's a project worth actually pursuing, 
this current version, apart from having terrible code design, is rudamentary and also contains soon to be fixed known bugs, most notably:
- Swaps are always pushed with thumbnail-swaps included, which causes fewer swaps to work than otherwise

I'm currently overhauling the entire codebase to bring it up to any actual standard on [full-backend-redesign](https://github.com/NotIPlayForFun/RL-Swapper/tree/full-backend-redesign)

The next commit will contain the overhauled code and all major bugs fixed.

<sup><sub>Let this be a lesson to never trust AI with anything that there is even a small chance you might want to pursure for any longer term. Turns out it still, for the most part, doesn't know how to code. I half debated starting anew rather than fixing this mess but sunk cost fallacy is real and here we are. Soon I'll be free from the torment...</sub></sup>

# RL-Swapper: A Rocket League Skin Swapper

<img width="700" alt="v0 1 0-add_new_swap_cropped" src="https://github.com/NotIPlayForFun/RL-Swapper/blob/main/resources/v0.1.0-Dashboard.png" />

## Swap your Rocket League Decals, Boosts, etc. for any item via an easy interface

I made this app because it was annoying to have to manually select files, copy, make backups, and keep track of changes. 

### Features
* Intuitive UI
* Easily prepare asset swaps (f.e., replace bubbles boost -> alpha boost)
* Push swaps to RL
* Revert swaps to automatic backups

All with a few button presses. Swaps are handled dynamically, no third-party downloads required.

<img width="600" alt="v0 1 0-add_new_swap_cropped" src="https://github.com/NotIPlayForFun/RL-Swapper/blob/main/resources/v0.1.0-add_new_swap_cropped.png" />

### Installation Instructions
1. Download the latest [`release`](https://github.com/NotIPlayForFun/RL-Swapper/releases/).
2. Run the installer.
3. Launch via the Desktop or Start Menu shortcut.

(*Developer alternative*: You should also be able to clone the repo and run interface.py directly, or compile using `pyinstaller rl-swapper.spec --clean`. This requires installing the dependencies and is currently untested.)
