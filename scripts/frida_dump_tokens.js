'use strict';
/* Dump decrypted ARCFOX login state from a running app via its own getters.
 * Keep captured output local; never commit secrets. */
var SPOOF_PROPS = true;
var BLOCK_APP_SELF_EXIT = true;

function spoofProps() {
    var libc = Process.getModuleByName('libc.so');
    var FAKE = { 'ro.debuggable': '0', 'ro.build.type': 'user', 'ro.build.tags': 'release-keys' };
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
            onEnter: function (a) { this.name = a[0]; this.value = a[1]; },
            onLeave: function (ret) {
                var n = applyFake(this.name, this.value);
                if (n >= 0) ret.replace(ptr(n));
            }
        });
    }
    var spr = libc.findExportByName('__system_property_read');
    if (spr) {
        Interceptor.attach(spr, {
            onEnter: function (a) { this.name = a[1]; this.value = a[2]; },
            onLeave: function (ret) {
                var n = applyFake(this.name, this.value);
                if (n >= 0) ret.replace(ptr(n));
            }
        });
    }
    console.log('[arcfox] property spoof ready');
}

function blockExit() {
    try {
        var Sys = Java.use('java.lang.System');
        Sys.exit.overload('int').implementation = function (code) {
            var isApp = false;
            try {
                var st = Java.use('java.lang.Throwable').$new().getStackTrace();
                for (var i = 0; i < st.length; i++) {
                    var cn = st[i].getClassName();
                    if (cn && cn.indexOf('com.bjev.arcfox.App') === 0) { isApp = true; break; }
                }
            } catch (e) {}
            if (isApp) { console.log('[arcfox] blocked App self-exit code=' + code); return; }
            return this.exit(code);
        };
    } catch (e) { console.log('[arcfox] exit hook fail ' + e); }
}

function tryGet(cls, method, ctx) {
    try {
        var C = Java.use(cls);
        var v = C[method](ctx);
        console.log('[GET] ' + cls + '.' + method + ' = ' + v);
    } catch (e) {
        console.log('[GET-ERR] ' + cls + '.' + method + ' : ' + e);
    }
}

function dumpPrefs(ctx, name) {
    try {
        var prefs = ctx.getSharedPreferences(name, 0);
        var all = prefs.getAll();
        var it = all.entrySet().iterator();
        console.log('[PREFS] ==== ' + name + ' ====');
        while (it.hasNext()) {
            var e = it.next();
            console.log('[PREFS] ' + name + ' :: ' + e.getKey() + ' => ' + e.getValue());
        }
        console.log('[PREFS] ==== end ' + name + ' ====');
    } catch (e) {
        console.log('[PREFS-ERR] ' + name + ' : ' + e);
    }
}

function main() {
    console.log('[arcfox] Java ready');
    blockExit();
    var ctx = null;
    var tries = 0;
    var timer = setInterval(function () {
        tries++;
        try {
            if (!ctx) {
                var AT = Java.use('android.app.ActivityThread');
                ctx = AT.currentApplication();
            }
            if (ctx) {
                console.log('[arcfox] context ready at try ' + tries + ' pkg=' + ctx.getPackageName());
                clearInterval(timer);
                Java.enumerateLoadedClasses({
                    onMatch: function (name) {
                        if (/SPHelper|Encrypt|Prefs|SaveInfo|UserInfo|Token|Login/i.test(name)) {
                            console.log('[CLASS] ' + name);
                        }
                    },
                    onComplete: function () { console.log('[CLASS] enum done'); }
                });
                tryGet('com.android.applibrary.utils.SPHelper', 'getAccessToken', ctx);
                tryGet('com.android.applibrary.utils.SPHelper', 'getRefreshToken', ctx);
                tryGet('com.android.applibrary.utils.SPHelper', 'getUserId', ctx);
                tryGet('com.android.applibrary.utils.SPHelper', 'getVin', ctx);
                tryGet('com.android.applibrary.utils.SPHelper', 'getPhone', ctx);
                tryGet('com.android.applibrary.utils.SPHelper', 'getIMEI', ctx);
                tryGet('com.android.beapplibrary.utils.SPHelper', 'getAccessToken', ctx);
                tryGet('com.android.beapplibrary.utils.SPHelper', 'getRefreshToken', ctx);
                tryGet('com.android.beapplibrary.utils.SPHelper', 'getUserId', ctx);
                dumpPrefs(ctx, 'saveInfo');
                dumpPrefs(ctx, 'AppConfig');
                dumpPrefs(ctx, 'userConfig<AID>');
                console.log('[arcfox] dump pass complete');
            }
        } catch (e) {
            console.log('[arcfox] main loop error: ' + e);
        }
        if (tries > 30) {
            console.log('[arcfox] giving up waiting for context');
            clearInterval(timer);
        }
    }, 1000);
}

function waitJava() {
    try {
        if (typeof Java !== 'undefined' && Java.available) { Java.perform(main); return; }
    } catch (e) {}
    setTimeout(waitJava, 100);
}

if (SPOOF_PROPS) spoofProps();
console.log('[arcfox] script loaded');
waitJava();
