FROM erplibre-base:12.0

ENV REPO_MANIFEST_URL https://github.com/agileops/ERPLibre.git
RUN cat /etc/os-release

ENV ADDONS_BASE_DIR /odoo

USER root

RUN mkdir ~/.ssh/ && echo "StrictHostKeyChecking no" >> ~/.ssh/config &&   apt update && apt install ssh-client  git -y --no-install-recommends && \
	rm -rf /var/lib/apt/lists/*

RUN cd ; mkdir -p .bin/ && \
	git config --global color.ui false && \
	git config --global user.email "foo@bar.io" && \
	git config --global user.name "Foo Bar" && \
	curl https://storage.googleapis.com/git-repo-downloads/repo > ~/.bin/repo && \
	chmod +x ~/.bin/repo && sed -i '1 s/python$/python3/' ~/.bin/repo && head ~/.bin/repo && \
	export PATH="${HOME}/.bin:${PATH}" && \
	mkdir -p $ADDONS_BASE_DIR && cd $ADDONS_BASE_DIR && \
	repo init -u $REPO_MANIFEST_URL  -b 12.0_repo  && \
	repo sync -j 4 -c

ADD repo_manifest_gen_org_prefix_path.py /root/.bin/
RUN chmod +x ~/.bin/repo_manifest_gen_org_prefix_path.py

RUN head /etc/odoo/odoo.conf && /root/.bin/repo_manifest_gen_org_prefix_path.py $ADDONS_BASE_DIR/addons  /etc/odoo/odoo.conf /etc/odoo/odoo.conf && head  /etc/odoo/odoo.conf

user odoo

ENTRYPOINT ["/entrypoint.sh"]
CMD ["odoo"]
