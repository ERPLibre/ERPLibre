# TODO
## Simplify push tag
For RELEASE.md, replace next value by a script to select all remote by manifest file.
Actually, need to push manually all different remote.
> ./.venv/repo forall -pc "git push ERPLibre --tags"

## Funding
- Add funding for MathBenTech and TechnoLibre

## Improve repo init usage
- Support run repo init without human interaction. Do we need to create a temporary user name?

## Improve repo sync usage
- Test repo sync with argument -d
- Test repo sync with argument -t SMART_TAG, like tag ERPLibre/v1.0.0

## Git diff
### Between 2 commits
- Show all modified file, files list.
- Show if probably has conflict if cherry-pick in wrong order,
- Show modify same line in different commit

## Development
### Run with another address ip than local
- Remove xmlrpc_interface in config file when running dev installation
- Improve config builder with a Python script

### Variable in new instance
- Add technique to add variable when create a new instance from config files
- Documentation for adding mail server, a guide for every one
