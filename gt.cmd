@echo off
rem Git wrapper
rem Author: Vlad Topan (vtopan/gmail)
rem Version: 0.1.2 (2019.07.19)

setlocal enabledelayedexpansion

if _%1_ == _am_ git commit --amend
if _%1_ == _b_ git branch|cat -n
if _%1_ == _c_ git commit -m "%2"
if _%1_ == _cd_ git clone --depth=1 "%2"
if _%1_ == _d_ git diff
if _%1_ == _i_ ( 
    echo === Branches ===
    git branch --color=always
    echo === Status ===
    git status -s
    echo === Log ===
    git log --oneline|head -n5
)
if _%1_ == _l_ git log --oneline --color=always
if _%1_ == _p_ git pull
if _%1_ == _pp_ ( git pull & git push )
if _%1_ == _P_ git push
if _%1_ == _s_ git status -s
if _%1_ == _sc_ git stash clear
if _%1_ == _S_ git stash
if _%1_ == _sp_ git stash pop
rem staged changes
if _%1_ == _t_ git diff --cached
if _%1_ == _u_ git reset HEAD~
rem unpushed commits
if _%1_ == _U_ git log --branches --not --remotes
if _%1_ == _?_ git show "%2"

:end
