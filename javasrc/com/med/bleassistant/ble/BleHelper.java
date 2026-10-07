package com.med.bleassistant.ble;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.content.Intent;
import android.location.LocationManager;
import android.os.Build;
import android.util.Log;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * BLE bridge between Python and the Android Bluetooth stack.
 *
 * NOTE: keep this file ASCII-only on purpose. javac uses the platform default
 * charset when no -encoding is given, so non-ASCII comments can break the build
 * on machines whose default charset is not UTF-8.
 *
 * WHY THIS FILE EXISTS:
 * PyJNIus can only implement Java interfaces; it cannot subclass a Java object.
 * Android's ScanCallback and BluetoothGattCallback are abstract classes, so
 * they cannot be implemented from Python. Both callbacks therefore live here in
 * Java, and the Python side only kicks off actions and polls the static state
 * below. No Java -> Python callback is needed, which also avoids threading
 * problems (BLE callbacks arrive on the Android main thread while Python runs
 * on its own thread).
 *
 * STATE CONTRACT (mirrored by constants in ble_android.py):
 *   scan: 0 idle, 1 running, 2 failed
 *   conn: 0 idle, 1 connecting, 2 connected, 3 disconnected, 4 failed
 */
public final class BleHelper {

    private static final String TAG = "BleHelper";

    public static final int SCAN_IDLE = 0;
    public static final int SCAN_RUNNING = 1;
    public static final int SCAN_FAILED = 2;

    public static final int CONN_IDLE = 0;
    public static final int CONN_CONNECTING = 1;
    public static final int CONN_CONNECTED = 2;
    public static final int CONN_DISCONNECTED = 3;
    public static final int CONN_FAILED = 4;

    private static final Object LOCK = new Object();

    /** address -> "name|address|rssi" */
    private static final Map<String, String> DEVICES = new LinkedHashMap<String, String>();

    private static volatile int scanState = SCAN_IDLE;
    private static volatile int scanError = 0;
    private static volatile int connState = CONN_IDLE;
    private static volatile int connStatus = 0;
    private static volatile int serviceCount = 0;
    private static volatile String connName = "";
    private static volatile String connAddress = "";

    private static BluetoothLeScanner scanner;
    private static boolean scanning = false;
    private static BluetoothGatt gatt;

    private BleHelper() {
    }

    // ------------------------------------------------------------------
    // Adapter / Bluetooth switch
    // ------------------------------------------------------------------
    public static BluetoothAdapter getAdapter(Context ctx) {
        try {
            BluetoothManager manager =
                    (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
            return manager == null ? null : manager.getAdapter();
        } catch (Throwable t) {
            Log.w(TAG, "getAdapter: " + t);
            return null;
        }
    }

    public static boolean isBluetoothEnabled(Context ctx) {
        BluetoothAdapter adapter = getAdapter(ctx);
        return adapter != null && adapter.isEnabled();
    }

    /** Shows the system "turn on Bluetooth" dialog. */
    public static void requestEnable(Context ctx) {
        try {
            Intent intent = new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(intent);
        } catch (Throwable t) {
            Log.w(TAG, "requestEnable: " + t);
        }
    }

    /**
     * Whether the system location switch is on. BLE scan results are suppressed by
     * Android when location services are off, unless BLUETOOTH_SCAN is declared with
     * usesPermissionFlags="neverForLocation". Used for the on-screen diagnostics only.
     */
    public static boolean isLocationEnabled(Context ctx) {
        try {
            LocationManager manager =
                    (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            if (manager == null) {
                return false;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                return manager.isLocationEnabled();
            }
            return manager.isProviderEnabled(LocationManager.GPS_PROVIDER)
                    || manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
        } catch (Throwable t) {
            Log.w(TAG, "isLocationEnabled: " + t);
            return false;
        }
    }

    // ------------------------------------------------------------------
    // BLE scan
    // ------------------------------------------------------------------
    private static final ScanCallback SCAN_CALLBACK = new ScanCallback() {
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            addResult(result);
        }

        @Override
        public void onBatchScanResults(List<ScanResult> results) {
            if (results == null) {
                return;
            }
            for (ScanResult result : results) {
                addResult(result);
            }
        }

        @Override
        public void onScanFailed(int errorCode) {
            scanError = errorCode;
            scanState = SCAN_FAILED;
            scanning = false;
        }
    };

    private static void addResult(ScanResult result) {
        if (result == null || result.getDevice() == null) {
            return;
        }
        BluetoothDevice device = result.getDevice();
        String address = device.getAddress();
        if (address == null || address.isEmpty()) {
            return;
        }
        String name = "";
        try {
            String raw = device.getName();
            if (raw != null) {
                name = raw.trim();
            }
        } catch (Throwable ignored) {
            // On Android 12+ reading the name throws unless BLUETOOTH_CONNECT
            // was granted. Missing names are simply left empty.
        }
        synchronized (LOCK) {
            DEVICES.put(address, name + "|" + address + "|" + result.getRssi());
        }
    }

    public static void clearDevices() {
        synchronized (LOCK) {
            DEVICES.clear();
        }
        scanError = 0;
        scanState = SCAN_IDLE;
    }

    /** Returns "name|address|rssi" entries for the Python side to poll. */
    public static String[] getDevices() {
        synchronized (LOCK) {
            return DEVICES.values().toArray(new String[0]);
        }
    }

    public static int getDeviceCount() {
        synchronized (LOCK) {
            return DEVICES.size();
        }
    }

    public static int getScanState() {
        return scanState;
    }

    public static int getScanError() {
        return scanError;
    }

    public static void startScan(Context ctx) {
        stopScan();
        BluetoothAdapter adapter = getAdapter(ctx);
        if (adapter == null) {
            scanError = -1;
            scanState = SCAN_FAILED;
            return;
        }
        if (!adapter.isEnabled()) {
            scanError = -2;
            scanState = SCAN_FAILED;
            return;
        }
        try {
            scanner = adapter.getBluetoothLeScanner();
        } catch (Throwable t) {
            scanner = null;
        }
        if (scanner == null) {
            scanError = -3;
            scanState = SCAN_FAILED;
            return;
        }
        ScanSettings settings = new ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build();
        try {
            scanner.startScan(null, settings, SCAN_CALLBACK);
            scanning = true;
            scanState = SCAN_RUNNING;
        } catch (Throwable t) {
            Log.w(TAG, "startScan: " + t);
            scanError = -4;
            scanState = SCAN_FAILED;
        }
    }

    public static void stopScan() {
        if (scanner != null && scanning) {
            try {
                scanner.stopScan(SCAN_CALLBACK);
            } catch (Throwable ignored) {
            }
        }
        scanning = false;
        if (scanState == SCAN_RUNNING) {
            scanState = SCAN_IDLE;
        }
    }

    // ------------------------------------------------------------------
    // GATT connection
    // ------------------------------------------------------------------
    private static final BluetoothGattCallback GATT_CALLBACK = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
            connStatus = status;
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                connState = CONN_CONNECTED;
                serviceCount = 0;
                try {
                    BluetoothDevice device = g.getDevice();
                    if (device != null) {
                        connAddress = device.getAddress();
                        String raw = device.getName();
                        connName = (raw == null) ? "" : raw.trim();
                    }
                    g.discoverServices();
                } catch (Throwable ignored) {
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                connState = CONN_DISCONNECTED;
                serviceCount = 0;
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int status) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                try {
                    serviceCount = g.getServices().size();
                } catch (Throwable ignored) {
                }
            }
        }
    };

    public static void connect(Context ctx, String address) {
        if (address == null || address.isEmpty()) {
            connState = CONN_FAILED;
            return;
        }
        BluetoothAdapter adapter = getAdapter(ctx);
        if (adapter == null) {
            connState = CONN_FAILED;
            return;
        }
        try {
            BluetoothDevice device = adapter.getRemoteDevice(address);
            connAddress = address;
            serviceCount = 0;
            connState = CONN_CONNECTING;
            gatt = device.connectGatt(ctx, false, GATT_CALLBACK);
            if (gatt == null) {
                connState = CONN_FAILED;
            }
        } catch (Throwable t) {
            Log.w(TAG, "connect: " + t);
            connState = CONN_FAILED;
        }
    }

    public static void disconnect() {
        stopScan();
        try {
            if (gatt != null) {
                gatt.disconnect();
                gatt.close();
            }
        } catch (Throwable ignored) {
        }
        gatt = null;
        connState = CONN_DISCONNECTED;
        serviceCount = 0;
    }

    public static int getConnState() {
        return connState;
    }

    public static int getConnStatus() {
        return connStatus;
    }

    public static int getServiceCount() {
        return serviceCount;
    }

    public static String getConnectedName() {
        return connName == null ? "" : connName;
    }

    public static String getConnectedAddress() {
        return connAddress == null ? "" : connAddress;
    }
}
