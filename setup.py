from distutils.core import setup

setup(
	name='PySpW',
	version='0.1.0',
	author='Kazuhiro Sakai',
	author_email='sakai@astro.isas.jaxa.jp',
	packages=[ 'pyspw' ],
	license='LICENSE.txt',
	description='Python SpaceWire Library',
	long_description=open('README.txt').read()
)