#!/usr/bin/env bash

echo "This will remove the following directories"
echo "This action could remove a production instance with ===> env_var.sh parameters <===, use with care"
echo "---> rm -rf ~/.poetry"
echo "---> rm -rf ~/.pyenv"

echo "Are you sure you want to proceed with destroy? [y/n]"
read answer
 if [ $answer == "y" ]
 then
   echo "Ok we destroy"
    # ./delete_production.sh
    # sudo rm -rf ~/.poetry
     #sudo rm -rf ~/.pyenv
 else
     echo "Ok we cancel Destroy sequence"
 fi
