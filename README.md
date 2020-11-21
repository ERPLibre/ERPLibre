# ERPLibre documentation
Select a guide to install your environment!

## Easy way to run locally
Clone the project
```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```
Support Ubuntu 18.04 and OSX
```bash
./script/install_dev.sh
./script/install_locally_prod.sh
```
Update your configuration if you need to run somehere than 127.0.0.1, file `config.conf`
```
#xmlrpc_interface = 127.0.0.1
#netrpc_interface = 127.0.0.1
```
Run
```bash
./run.sh
```

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
