'use strict';
/*
 * Frida hook for ARCFOX 3.4.x on a debuggable/rooted device or emulator.
 *
 * Usage (spawn):
 *   frida -U -f com.bjev.arcfox -l scripts/frida_arcfox_runtime.js
 * or attach to a running process after it has passed startup:
 *   frida -U -n com.bjev.arcfox -l scripts/frida_arcfox_runtime.js
 *
 * What it does:
 *   1. Spoofs ro.debuggable/ro.build.type/ro.build.tags so the packer does not
 *      self-exit on a userdebug image.
 *   2. Blocks System.exit() only when the stack belongs to the App self-exit
 *      path (App.onCreate). This keeps the app alive without globally
 *      breaking normal process shutdown.
 *   3. Logs registerEncrypt/registerDecrypt call sites and handler classes.
 *   4. Logs EncryptionCtrlReq setter values (the REST control AEAD envelope).
 *
 * No secrets are hard-coded. Keep captured output local and out of git.
 */

var SPOOF_PROPS = true;
var BLOCK_APP_SELF_EXIT = true;
var HOOK_HANDLER_REGISTER = true;
var HOOK_ENCRYPTION_CTRL_REQ = true;

var logger = {
    log: function (m) { console.log('[arcfox] ' + m); },
    error: function (m) { console.error('[arcfox] ' + m); }
};

function spoofProps() {
    var libc = Process.getModuleByName('libc.so');
    var FAKE = {
        'ro.debuggable': '0',
        'ro.build.type': 'user',
        'ro.build.tags': 'release-keys'
    };

    function applyFake(namePtr, valuePtr) {
        try {
            var name = namePtr.readCString();
            if (name && FAKE[name] !== undefined) {
                valuePtr.writeUtf8String(FAKE[name]);
                return FAKE[name].length;
            }
        } catch (e) {}
        return -1;
    }

    var spg = libc.findExportByName('__system_property_get');
    if (spg) {
        Interceptor.attach(spg, {
            onEnter: function (args) { this.name = args[0]; this.value = args[1]; },
            onLeave: function (retval) {
                var n = applyFake(this.name, this.value);
                if (n >= 0) retval.replace(ptr(n));
            }
        });
    }

    var spr = libc.findExportByName('__system_property_read');
    if (spr) {
        Interceptor.attach(spr, {
            onEnter: function (args) { this.name = args[1]; this.value = args[2]; },
            onLeave: function (retval) {
                var n = applyFake(this.name, this.value);
                if (n >= 0) retval.replace(ptr(n));
            }
        });
    }
    logger.log('property spoof ready');
}

function stackSummary() {
    var lines = [];
    try {
        var st = Java.use('java.lang.Throwable').$new().getStackTrace();
        for (var i = 0; i < Math.min(st.length, 12); i++) {
            lines.push(st[i].getClassName() + '.' + st[i].getMethodName() +
                '(' + st[i].getFileName() + ':' + st[i].getLineNumber() + ')');
        }
    } catch (e) {}
    return lines.join('\n    ');
}

function hookBlockAppSelfExit() {
    try {
        var Sys = Java.use('java.lang.System');
        Sys.exit.overload('int').implementation = function (code) {
            var isAppSelfExit = false;
            try {
                var st = Java.use('java.lang.Throwable').$new().getStackTrace();
                for (var i = 0; i < st.length; i++) {
                    var cn = st[i].getClassName();
                    if (cn && cn.indexOf('com.bjev.arcfox.App') === 0) {
                        isAppSelfExit = true;
                        break;
                    }
                }
            } catch (e) {}
            logger.log('System.exit(' + code + ') appSelfExit=' + isAppSelfExit);
            if (isAppSelfExit) {
                logger.log('blocked App self-exit');
                return;
            }
            return this.exit(code);
        };
        logger.log('App self-exit blocker ready');
    } catch (e) {
        logger.error('System.exit hook failed: ' + e);
    }
}

function hookHandlerRegister() {
    try {
        var R = Java.use('com.huawei.business.remotecontrol.api.a.a');
        R.registerEncrypt.implementation = function (h) {
            logger.log('registerEncrypt handlerClass=' +
                (h && h.$className ? h.$className : '?') +
                ' value=' + h);
            logger.log('registerEncrypt stack:\n    ' + stackSummary());
            return this.registerEncrypt(h);
        };
        R.registerDecrypt.implementation = function (h) {
            logger.log('registerDecrypt handlerClass=' +
                (h && h.$className ? h.$className : '?') +
                ' value=' + h);
            logger.log('registerDecrypt stack:\n    ' + stackSummary());
            return this.registerDecrypt(h);
        };
        logger.log('registerEncrypt/registerDecrypt hooks ready');
    } catch (e) {
        logger.error('register hook failed (class not loaded yet): ' + e);
    }
}

function hookEncryptionCtrlReq() {
    try {
        var E = Java.use('com.huawei.business.remotecontrol.entity.request.EncryptionCtrlReq');
        var fields = ['algorithm', 'iv', 'nonce', 'salt', 'aad', 'tag', 'content', 'contentId'];
        fields.forEach(function (name) {
            var setter = 'set' + name.charAt(0).toUpperCase() + name.slice(1);
            try {
                E[setter].overloads.forEach(function (ov) {
                    ov.implementation = function (value) {
                        logger.log('EncryptionCtrlReq.' + setter + '(' + value + ')');
                        return ov.apply(this, arguments);
                    };
                });
            } catch (e) {}
        });
        var setTs = E.setTimestamp;
        if (setTs) {
            setTs.overloads.forEach(function (ov) {
                ov.implementation = function (value) {
                    logger.log('EncryptionCtrlReq.setTimestamp(' + value + ')');
                    return ov.apply(this, arguments);
                };
            });
        }
        logger.log('EncryptionCtrlReq setter hooks ready');
        return true;
    } catch (e) {
        logger.error('EncryptionCtrlReq hook failed (class not loaded yet): ' + e);
        return false;
    }
}

function tryHookEncryptionCtrlReq() {
    if (hookEncryptionCtrlReq()) {
        return true;
    }
    var tries = 0;
    var timer = setInterval(function () {
        tries++;
        if (hookEncryptionCtrlReq() || tries > 30) {
            clearInterval(timer);
        }
    }, 2000);
    return false;
}

function main() {
    logger.log('Java ready');
    if (BLOCK_APP_SELF_EXIT) hookBlockAppSelfExit();
    if (HOOK_HANDLER_REGISTER) hookHandlerRegister();
    if (HOOK_ENCRYPTION_CTRL_REQ) tryHookEncryptionCtrlReq();
}

function waitForJava() {
    try {
        if (typeof Java !== 'undefined' && Java.available) {
            Java.perform(main);
            return;
        }
    } catch (e) {}
    setTimeout(waitForJava, 100);
}

if (SPOOF_PROPS) spoofProps();
logger.log('script loaded');
waitForJava();
