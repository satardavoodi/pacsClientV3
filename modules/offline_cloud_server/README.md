# Offline Cloud Server

This module groups the Offline Cloud Server feature that lets AI PACS or local downloaded studies be exported into a package folder and later synced back manually.

The package is identified by a root `manifest.json`, and the module exposes:

- service helpers for package export, validation, and import
- dialogs for managing Offline Cloud servers and inspecting package JSON

The actual transfer of the package folder can happen through USB, Dropbox, Google Drive, or any similar external mechanism.
