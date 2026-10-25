from setuptools import setup


setup(
	name="domino-web",
	version="0.1.0",
	description="An experimental Python web framework built on Flask",
	long_description=open("README.md", encoding="utf-8").read(),
	long_description_content_type="text/markdown",
	author="kegsmr",
	url="https://github.com/kegsmr/domino",
	license="MIT",
	packages=["domino"],
	package_data={"domino": ["core.js", "tags.pyi"]},
	python_requires=">=3.9",
	install_requires=["Flask>=2.2", "pymongo>=4"],
	extras_require={"test": ["pytest"]},
)
