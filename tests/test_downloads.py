"""Domino's downloads (MongoDB, Tailwind CSS) when Python can't verify certificates by itself."""

import ssl
import urllib.error
import urllib.request

import pytest

from domino import devmongo, util


def certificate_error():

	return urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed: unable to get local issuer certificate"))


def test_a_certificate_the_system_cant_verify_is_tried_with_certifi(monkeypatch):

	certifi = pytest.importorskip("certifi")
	calls = []

	def urlopen(url, timeout=None, context=None):
		calls.append(context)
		if context is None:
			raise certificate_error()
		return "opened"

	monkeypatch.setattr(urllib.request, "urlopen", urlopen)

	assert util.urlopen("https://downloads.mongodb.org/full.json") == "opened"
	assert calls[0] is None and isinstance(calls[1], ssl.SSLContext)
	assert certifi.where()


def test_other_errors_are_not_retried(monkeypatch):

	calls = []

	def urlopen(url, timeout=None, context=None):
		calls.append(context)
		raise urllib.error.URLError("Name or service not known")

	monkeypatch.setattr(urllib.request, "urlopen", urlopen)

	with pytest.raises(urllib.error.URLError):
		util.urlopen("https://downloads.mongodb.org/full.json")
	assert calls == [None]


def test_a_failed_lookup_says_what_to_do_instead_of_a_traceback(monkeypatch):

	def urlopen(url, timeout=None, context=None):
		raise certificate_error()

	monkeypatch.setattr(urllib.request, "urlopen", urlopen)

	with pytest.raises(devmongo.DevMongoError) as error:
		devmongo.fetch_index()

	message = str(error.value)
	assert "Couldn't look up MongoDB's releases" in message
	assert "Install Certificates.command" in message and "mongo.url" in message
