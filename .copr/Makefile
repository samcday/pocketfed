srpm:
	sed -i -e "s/%autorelease/$(shell date +%s)%{?dist}/" -e "s/%timestamp/$(shell date +%s)/" *.spec
	dnf install -y rpkg rpmdevtools
	spectool -g *.spec
	if test -f sources.sha256; then sha256sum --check sources.sha256; fi
	rpkg srpm --outdir=.
	mv *.src.rpm $(outdir)/
