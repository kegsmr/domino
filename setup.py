from setuptools import setup


setup(
	name="domino",
	version="0.1.0",
	description="An experimental Python web framework built on Flask",
	long_description=open("README.md", encoding="utf-8").read(),
	long_description_content_type="text/markdown",
	author="kegsmr",
	url="https://github.com/kegsmr/domino",
	license="MIT",
	packages=["domino"],
	package_data={"domino": ["core.js"]},
	python_requires=">=3.8",
	install_requires=["Flask>=2.2"],
	extras_require={"test": ["pytest"]},
)
