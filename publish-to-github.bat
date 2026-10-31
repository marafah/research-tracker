@echo off
REM Publish Research Tracker to your GitHub account (run once).
REM Needs: Git for Windows (https://git-scm.com/download/win) and GitHub CLI (https://cli.github.com)
cd /d "%~dp0"
where git >nul 2>nul || (echo [!] Please install Git first: https://git-scm.com/download/win & pause & exit /b 1)
where gh  >nul 2>nul || (echo [!] Please install GitHub CLI first: https://cli.github.com & pause & exit /b 1)

gh auth status >nul 2>nul || gh auth login --hostname github.com --git-protocol https --web
if not exist .git git init -b main
git config user.name  >nul 2>nul || for /f "delims=" %%u in ('gh api user --jq .login') do git config user.name "%%u"
git config user.email >nul 2>nul || for /f "delims=" %%u in ('gh api user --jq .login') do git config user.email "%%u@users.noreply.github.com"
git add -A
git commit -m "Research Tracker: initial release" || echo (nothing new to commit)

git remote get-url origin >nul 2>nul && (git push -u origin main) || (gh repo create research-tracker --public --description "Open-source research publication tracker (Arabic/English)" --source=. --remote=origin --push)
echo.
echo Done. Opening your repository...
gh repo view --web
pause
