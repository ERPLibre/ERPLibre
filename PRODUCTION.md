# ERPLibre

## Move database prod to dev

When moving database prod to your dev environment, you want to remove email servers, and install user test to test the database.
Run :
> -c config.conf --stop-after-init -i user_test,disable_mail_server --dev all -d DATABASE