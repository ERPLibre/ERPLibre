# ERPLibre documentation
Select a guide to install your environment.

## Easy way to run locally
Into Ubuntu, minimal dependency:
```bash
sudo apt install make git
```
Clone the project:
```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```
Support Ubuntu 18.04, 20.04 and OSX. The installation duration is more than 30 minutes.
```bash
make install
```
Update your configuration if you need to run from another interface than 127.0.0.1, file `config.conf`
```
#xmlrpc_interface = 127.0.0.1
#netrpc_interface = 127.0.0.1
```
Ready to execute:
```bash
make run
```

## Easy way to run docker
First, install dependencies to run docker, check script `./script/install_ubuntu_docker.sh`. You need docker and docker-compose.

The docker volume is binded to the directory name, therefore create a unique directory name and run:
```bash
wget https://raw.githubusercontent.com/ERPLibre/ERPLibre/v1.2.1/docker-compose.yml
docker-compose up -d
```

For more information, read [Docker guide](./docker/README.md).

## Discover guide
[Guide to run ERPLibre in discover to learn it](./doc/DISCOVER.md).

## Production guide
[Guide to run ERPLibre in production server](./doc/PRODUCTION.md).

## Development guide
[Guide to run ERPLibre in development environment](./doc/DEVELOPMENT.md).

# Execution
[Guide to run ERPLibre with different case](./doc/RUN.md).

# git-repo
To change repository like addons, see [GIT_REPO.md](doc/GIT_REPO.md)

# Test
Execute ERPLibre test with his code generator.
```bash
time make test
```
