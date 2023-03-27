#! /bin/bash
sudo apt-get update
sudo apt-get -y upgrade

# create new user chargefw2
sudo useradd chargefw2
sudo mkdir /home/chargefw2

# install apache2
sudo apt-get install -y apache2
# sudo reboot

# install mod_wsgi
sudo apt-get install -y libapache2-mod-wsgi-py3

# install flask
sudo apt install -y python3-flask

# install pip
sudo apt install -y python3-pip

# chargefw2 deployment
# boost
sudo apt-get install -y libboost-filesystem-dev libboost-system-dev libboost-program-options-dev
# cmake
sudo apt-get install -y cmake
# g++
sudo apt-get install -y g++
# eigen
sudo apt-get install -y libeigen3-dev
# fmt
sudo apt-get install -y libfmt-dev
# JSON for Modern C++: 
sudo apt-get install -y nlohmann-json3-dev
# pybind11
sudo apt-get install -y python3-pybind11
# clang
sudo apt-get install -y clang
# gemmi
# git clone --depth 1 https://github.com/project-gemmi/gemmi.git
# cp -r gemmi/include/gemmi /usr/include
sudo apt-get install -y gemmi-dev
sudo apt install -y gemmi
# nanoflann
# git clone --depth 1 --branch v1.3.2 https://github.com/jlblancoc/nanoflann.git /usr/include
sudo apt-get install -y libnanoflann-dev
# pegl
sudo apt-get install -y tao-pegtl-dev

# chargefw2
sudo apt install -y git
sudo? git clone --depth 1 https://github.com/LenkaPt/ChargeFW2.git
cd ChargeFW2
sudo? mkdir build
cd build
sudo? cmake .. -DCMAKE_BUILD_TYPE=Release
make
sudo make install

# export Python PATH variable TODO pripsat do .bashrc
export PYTHONPATH=/usr/local/lib

# pdb2pqr installation
sudo pip install pdb2pqr

# flask-restx installation
sudo pip install flask-restx

# openbabel installation
sudo apt-get install -y openbabel

# flask Limiter
# sudo pip install Flask-Limiter

# dos2unix installation
sudo apt-get install -y dos2unix

# API
sudo mkdir /home/chargefw2/api_acc2
sudo git clone https://github.com/LenkaPt/AtomicChargeCalculatorAPI.git /home/chargefw2/api_acc2
sudo mkdir /home/tmp
sudo chown -R chargefw2:chargefw2 /home/chargefw2
sudo chown -R chargefw2:chargefw2 /home/tmp

# enable api configuration
sudo mv /home/chargefw2/api_acc2/utils/api_acc2.conf /etc/apache2/sites-available/
cd /etc/apache2/sites-available
sudo a2ensite api_acc2.conf

# restart apache2
sudo service apache2 restart







