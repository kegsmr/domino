from setuptools import setup


setup(
	name="domino-web",
	version="0.2.0",
	description="An experimental Python web framework built on Flask",
	long_description=open("README.md", encoding="utf-8").read(),
	long_description_content_type="text/markdown",
	author="kegsmr",
	url="https://github.com/kegsmr/domino",
	license="MIT",
	packages=["domino"],
	package_data={"domino": ["core.js", "debug.js", "tags.pyi"]},
	python_requires=">=3.9",
	install_requires=["Flask>=2.2", "pymongo>=4", "uvicorn[standard]>=0.24", "a2wsgi>=1.7"],
	extras_require={"test": ["pytest", "websockets"]},
	entry_points={
		"console_scripts": ["domino=domino.cli:main"],
		# pytest finds tests next to their page (pages/about_test.py) with a `page` fixture
		"pytest11": ["domino=domino.pytest_plugin"],
	},
)
