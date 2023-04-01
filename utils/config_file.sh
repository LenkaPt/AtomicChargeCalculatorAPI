#! /bin/bash
sudo apt-get update
sudo apt-get -y upgrade

# create new user api_acc2
sudo useradd api_acc2
sudo mkdir /home/api_acc2

# install apache2, mod_wsgi
sudo apt-get install -y apache2 libapache2-mod-wsgi-py3

# install flask, pip
sudo apt install -y python3-flask python3-pip


# chargefw2 deployment
# boost
sudo apt-get install -y libboost-filesystem-dev libboost-system-dev libboost-program-options-dev
sudo apt-get install -y cmake g++ libeigen3-dev libfmt-dev nlohmann-json3-dev python3-pybind11
sudo apt-get install -y clang gemmi-dev gemmi libnanoflann-dev tao-pegtl-dev

# chargefw2
sudo apt install -y git
git clone --depth 1 https://github.com/LenkaPt/ChargeFW2.git
cd ChargeFW2
mkdir build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
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

# dos2unix installation
sudo apt-get install -y dos2unix

# API
sudo mkdir /home/api_acc2/api_acc2/logs
sudo git clone https://github.com/LenkaPt/AtomicChargeCalculatorAPI.git /home/api_acc2/api_acc2
sudo mkdir /home/tmp
sudo chown -R api_acc2:api_acc2 /home/api_acc2
sudo chown -R api_acc2:api_acc2 /home/tmp

# enable api configuration
sudo mv /home/api_acc2/api_acc2/utils/api_acc2.conf /etc/apache2/sites-available/
cd /etc/apache2/sites-available
sudo a2ensite api_acc2.conf

# restart apache2
sudo service apache2 restart







