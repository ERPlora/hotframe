"""
discovery — module filesystem scanning and kernel module bootstrapping.

``scan`` walks a modules directory and returns a ``DiscoveryResult``
describing every found module (entry point, manifest, template dirs,
migration dirs). ``boot_kernel_modules`` is called once at startup to
import and activate the built-in kernel modules (assistant, etc.) that
ship inside the Docker image and are always present regardless of hub
configuration.

Key exports::

    from hotframe.discovery.scanner import scan, DiscoveryResult
    from hotframe.discovery.bootstrap import boot_kernel_modules

Usage::

    result = scan(Path("/app/modules"), module_id="sales")
    await boot_kernel_modules(app, engine, settings)
"""
