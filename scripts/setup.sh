#!/usr/bin/env bash
# One-shot setup for Ubuntu 24.04 (native or WSL2) with ROS 2 Jazzy already installed.
# Installs the ROS packages this workspace uses, the optional AI-agent dependencies, and builds the workspace.
#   bash scripts/setup.sh            # ROS deps + build
#   bash scripts/setup.sh --agent    # also install Ollama + qwen2.5:3b and the Anthropic SDK
set -euo pipefail
WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f /opt/ros/jazzy/setup.bash ] || { echo "ROS 2 Jazzy not found in /opt/ros/jazzy (see docs.ros.org/en/jazzy/Installation.html)"; exit 1; }

echo "== ROS packages =="
sudo apt-get update
sudo apt-get install -y \
  ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox \
  ros-jazzy-ros2-control ros-jazzy-ros2-controllers ros-jazzy-ros2controlcli \
  ros-jazzy-robot-state-publisher ros-jazzy-joint-state-publisher ros-jazzy-tf2-tools \
  ros-jazzy-webots-ros2 python3-colcon-common-extensions python3-pytest python3-yaml zstd

if [[ "${1:-}" == "--agent" ]]; then
  echo "== AI agent: local model (Ollama + qwen2.5:3b) and Anthropic SDK =="
  command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
  ollama pull qwen2.5:3b
  pip3 install --user --break-system-packages anthropic
fi

echo "== Build =="
cd "$WS"
source /opt/ros/jazzy/setup.bash
colcon build
echo
echo "Done. In every new terminal:  source /opt/ros/jazzy/setup.bash && source $WS/install/setup.bash"
echo "Webots itself is installed separately (cyberbotics.com); on WSL install the Windows version."
