## This command disables User Account Control to run the script without user interaction, it is enabled at the end of the script.
## To avoid security concerns you can comment it if you prefer, otherwhise please check the software you install is safe and use this command at your own risk.
Disable-UAC
$Boxstarter.AutoLogin = $false
# Install git and clone repository containing scripts and config files
# TODO: see how to improve install that by using chezmoi (choco install -y chezmoi)
choco install -y git --params "/GitOnlyOnPath /NoShellIntegration /WindowsTerminal"
choco install -y nssm
choco install -y python
RefreshEnv
git clone https://github.com/SonixDev131/lab-agent.git "$env:USERPROFILE\lab-agent"

# Install python dependencies
pip install -r "$env:USERPROFILE\lab-agent\requirements.txt"

# Start service
nssm install "agent" python "$env:USERPROFILE\lab-agent\main.py"
nssm start agent

#--- reenabling critial items ---
Enable-UAC